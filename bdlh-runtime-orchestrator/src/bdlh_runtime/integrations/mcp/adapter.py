"""MCP 适配器：统一能力 → 原始工具调用的编排层。

MarketDataGateway 通过本适配器调用 MCP，不直接持有 McpClient。适配器职责：
1. 按路由策略选首选 MCP/工具/source；
2. 翻译统一参数为目标工具参数（interval vs period）；
3. 首选失败时切 fallback（最多 1 次）；
4. 把原始响应交给 normalizer 标准化为 Observation。

适配器不做：服务端吞错识别（normalizer 做）、预算扣减（Gateway 做）、
Observation 标准化（normalizer 做）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC
from typing import Any
from uuid import uuid4

from bdlh_runtime.contracts.observation import DataQuality, Observation, ProvenanceRecord

from .client import McpClient, create_mcp_client
from .routing_policy import (
    FINANCIAL_STATEMENT_ROUTES,
    RoutePolicy,
    RouteTarget,
    get_route,
    translate_arguments,
)

logger = logging.getLogger("bdlh_runtime.mcp.adapter")


class McpGatewayAdapter:
    """统一能力执行器：编排路由、翻译、调用和 fallback。

    持有所有 MCP 服务的 client 实例（按 mcp 名索引），在 execute 时按路由
    策略选择目标。client 实例由上层（Application Runtime）在启动时创建并
    注入，适配器不负责连接管理。
    """

    def __init__(self, clients: dict[str, McpClient]):
        """注入已初始化的 client 字典，key 为 MCP 名。

        例：{"cn-financial-mcp": SseMcpClient(...), "akshare-one-mcp": StreamableHttpMcpClient(...)}
        """
        self._clients = clients

    async def execute(
        self,
        capability: str,
        arguments: dict[str, Any],
        *,
        run_id: str = "",
    ) -> Observation:
        """执行一个统一能力，返回标准化 Observation。

        流程：查路由 → 翻译参数 → 调首选 → 失败则调 fallback → 包装结果。
        服务端吞错（{"error":true}）不在这里判定，由调用方经 normalizer
        二次处理；本方法只关注协议层错误和连接失败。
        """
        if capability == "market.get_financial_statements":
            return await self._execute_financial_statements(arguments, run_id)

        policy = get_route(capability)
        if policy is None:
            return _failed_observation(capability, f"未注册的统一能力: {capability}", run_id)

        # 尝试首选
        primary_obs = await self._try_target(capability, policy.primary, arguments, run_id)
        if primary_obs is not None:
            return primary_obs

        # 首选失败（网络异常/协议错误/服务端吞错），尝试 fallback（最多 1 次）。
        # 审查文档 §4.2：协议错误和吞错都必须视为一次失败尝试，触发备用源。
        if policy.fallback is not None:
            logger.info("能力 %s 首选失败，切换 fallback (mcp=%s)", capability, policy.fallback.mcp)
            result = await self._try_target(capability, policy.fallback, arguments, run_id, fallback=True)
            if result is not None:
                return result

        # 两者都失败：写入 known_unavailable 语义（data_quality）
        logger.warning(
            "能力 %s 主备均不可用 (primary=%s, fallback=%s)",
            capability,
            policy.primary.mcp,
            policy.fallback.mcp if policy.fallback else "none",
        )
        return _failed_observation(
            capability,
            f"主备均不可用: primary={policy.primary.mcp}, fallback={policy.fallback.mcp if policy.fallback else 'none'}",  # noqa: E501 —— 单条中文知识内容串，拆行反而破坏可读性
            run_id,
            known_unavailable=True,
        )

    async def _execute_financial_statements(
        self,
        arguments: dict[str, Any],
        run_id: str,
    ) -> Observation:
        """并行取得三大报表；每张表独立执行主备降级。"""

        async def fetch(name: str, policy: RoutePolicy) -> tuple[str, Observation | None]:
            result = await self._try_target(
                "market.get_financial_statements",
                policy.primary,
                arguments,
                run_id,
            )
            if result is None and policy.fallback is not None:
                result = await self._try_target(
                    "market.get_financial_statements",
                    policy.fallback,
                    arguments,
                    run_id,
                    fallback=True,
                )
            return name, result

        fetched = await asyncio.gather(*(fetch(name, policy) for name, policy in FINANCIAL_STATEMENT_ROUTES.items()))
        statements: dict[str, Any] = {}
        provenance: list[ProvenanceRecord] = []
        missing: list[str] = []
        for name, observation in fetched:
            if observation is None:
                missing.append(name)
                continue
            provenance.extend(observation.provenance)
            raw_text = observation.data.get("raw_text", "") if isinstance(observation.data, dict) else ""
            try:
                statements[name] = json.loads(raw_text)
            except (json.JSONDecodeError, TypeError):
                statements[name] = raw_text

        if not statements:
            return _failed_observation(
                "market.get_financial_statements",
                "三大财务报表主备数据源均不可用",
                run_id,
                known_unavailable=True,
            )

        completeness = len(statements) / len(FINANCIAL_STATEMENT_ROUTES)
        status = "SUCCESS" if not missing else "PARTIAL"
        return Observation(
            observation_id=str(uuid4()),
            capability="market.get_financial_statements",
            status=status,
            data={"raw_text": json.dumps(statements, ensure_ascii=False)},
            data_quality=DataQuality(
                completeness=completeness,
                quality_status="OK" if not missing else "PARTIAL",
                known_unavailable=[f"financial.{name}" for name in missing],
            ),
            provenance=provenance,
            error_code="FINANCIAL_STATEMENTS_PARTIAL" if missing else None,
            error_message=f"缺少报表: {', '.join(missing)}" if missing else None,
        )

    async def _try_target(
        self,
        capability: str,
        target: RouteTarget,
        unified_args: dict[str, Any],
        run_id: str,
        *,
        fallback: bool = False,
    ) -> Observation | None:
        """尝试单个路由目标。成功返回 Observation，失败返回 None。"""
        client = self._clients.get(target.mcp)
        if client is None:
            logger.warning("MCP %s 未注册 client", target.mcp)
            return None

        # 翻译参数 + 注入 source
        tool_args = translate_arguments(capability, unified_args)
        if target.source is not None:
            tool_args["source"] = target.source

        t0 = time.time()
        try:
            raw = await client.call_tool(target.tool, tool_args)
            elapsed = time.time() - t0
            elapsed_ms = int(elapsed * 1000)
        except Exception as exc:
            logger.warning("MCP 调用失败 capability=%s mcp=%s tool=%s: %s", capability, target.mcp, target.tool, exc)
            return None

        # 提取响应文本（normalizer 后续解析吞错）
        text = raw.get("text", "")
        is_error = raw.get("is_error", False)

        # 协议层错误（工具抛异常）→ 视为失败尝试，返回 None 触发 fallback
        if is_error:
            logger.warning("MCP 协议层错误 capability=%s mcp=%s: %s", capability, target.mcp, text[:200])
            return None

        # 服务端吞错（error:true 藏在正常响应里）→ 同样视为失败尝试，
        # 返回 None 触发 fallback。审查文档 §4.2 要求吞错必须触发备用源。
        if _detect_swallowed_error(text) is not None:
            logger.warning("MCP 服务端吞错 capability=%s mcp=%s: %s", capability, target.mcp, text[:150])
            return None

        # 成功：包 raw_text 供 normalizer 按 capability 解析为业务数据
        return Observation(
            observation_id=str(uuid4()),
            capability=capability,
            status="SUCCESS",
            data={"raw_text": text, "source_used": target.source},
            data_quality=DataQuality(completeness=1.0, quality_status="OK"),
            provenance=[_provenance(target, run_id, elapsed_ms, fallback, raw_text=text)],
        )


def _provenance(
    target: RouteTarget,
    run_id: str,
    elapsed_ms: int,
    fallback: bool,
    raw_text: str = "",
) -> ProvenanceRecord:
    """构建单条溯源记录（审查文档 §6.1：补耗时/原始引用）。

    raw_reference 只保留原始响应的受控引用（截断），不直接进 AnalysisInput。
    """
    from datetime import datetime

    return ProvenanceRecord(
        source=target.mcp,
        tool=target.tool,
        request_id=run_id or None,
        retrieved_at=datetime.now(UTC).isoformat(),
        elapsed_ms=elapsed_ms,
        fallback_used=fallback,
        raw_reference=raw_text[:200] if raw_text else None,
    )


def _failed_observation(
    capability: str,
    message: str,
    run_id: str,
    *,
    known_unavailable: bool = False,
) -> Observation:
    """构建失败 Observation。

    known_unavailable=True 时在 data_quality.known_unavailable 里记录该能力
    ——审查文档 §4.2 要求主备均失败时写入 known_unavailable，供分析层
    如实标记"该数据域不可用"而非编造。
    """
    dq = DataQuality(quality_status="INVALID")
    if known_unavailable:
        dq = DataQuality(quality_status="INVALID", known_unavailable=[capability])
    return Observation(
        observation_id=str(uuid4()),
        capability=capability,
        status="FAILED",
        data=None,
        data_quality=dq,
        provenance=[],
        error_code="MCP_UNAVAILABLE",
        error_message=message,
    )


def _detect_swallowed_error(raw_text: str) -> str | None:
    """检测服务端吞错（error:true 藏在正常响应里）。

    与 normalizer 的检测逻辑一致，但这里只做"是否失败"判定（用于 fallback
    决策），业务解析仍由 normalizer 完成——避免重复解析。
    """
    import json

    if not raw_text:
        return None
    stripped = raw_text.strip()
    # 部分 MCP 服务把工具异常包装成普通文本，同时协议层仍返回 isError=false。
    # 这类响应必须在 Adapter 层判为失败，才能触发备用数据源。
    text_error_prefixes = (
        "Error calling tool ",
        "Error executing tool ",
        "Tool execution failed",
    )
    if stripped.startswith(text_error_prefixes):
        return stripped
    try:
        parsed: Any = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(parsed, dict) and parsed.get("error") is True:
        return str(parsed.get("message", "未知错误"))
    if isinstance(parsed, list) and parsed:
        first = parsed[0]
        if isinstance(first, dict) and first.get("error") is True:
            return str(first.get("message", "未知错误"))
    return None


def create_adapter_from_settings(settings: Any) -> McpGatewayAdapter:
    """从 Settings 创建适配器，自动按传输类型初始化两个 MCP client。

    在 Application Runtime 启动时调用一次，缓存返回的适配器实例。
    """
    clients: dict[str, McpClient] = {
        "cn-financial-mcp": create_mcp_client(
            settings.mcp_cn_financial.transport,
            settings.mcp_cn_financial.endpoint,
            settings.mcp_cn_financial.timeout_seconds,
        ),
        "akshare-one-mcp": create_mcp_client(
            settings.mcp_akshare_one.transport,
            settings.mcp_akshare_one.endpoint,
            settings.mcp_akshare_one.timeout_seconds,
        ),
    }
    return McpGatewayAdapter(clients)
