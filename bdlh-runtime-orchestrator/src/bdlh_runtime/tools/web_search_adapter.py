"""bdlh-web-search-adapter 适配器。

网络搜索必须经由 bdlh-web-search-adapter 服务读取（架构文档 §13.4）：
Python 不允许绕过 wrapper 直接调用 SearXNG 或搜索引擎。

设计原则（与 Java adapter、MCP adapter 一致）：
- 统一能力 research.web_search → bdlh-web-search-adapter HTTP API 的翻译在 Adapter 内完成；
- wrapper 返回结果转换为 Observation，不允许 Graph 节点直接拼接搜索 JSON；
- **禁止 mock 降级**（G3）：未配置或调用失败一律返回 UNAVAILABLE；
- **只处理 research.web_search**。``research.deep_search`` 是独立复合 Capability
  （ADR-016），不得在本 Adapter 内静默升档或转发。

与 Java adapter 的差异（bdlh-web-search-adapter 接口特性）：
- 鉴权：双 header（x-agent-id + x-search-token）而非 Bearer；
- 请求体：批量 tasks 结构 {schemaVersion, tasks:[{taskId, query, ...}]}；
- 超时：20s（wrapper 内部已有 10s 上游超时，外层给余量）。
"""

from __future__ import annotations

import logging
from datetime import UTC
from typing import Any, Protocol
from uuid import uuid4

from bdlh_runtime.contracts.observation import DataQuality, Observation, ProvenanceRecord

logger = logging.getLogger("bdlh_runtime.tools.web_search")


class WebSearchAdapter(Protocol):
    """网络搜索必须经由 bdlh-web-search-adapter 服务。"""

    async def execute(self, capability: str, arguments: dict) -> Observation:
        """调用白名单 web-search API 并转换为 Observation。"""
        ...


# web-search 白名单能力，Adapter 只允许这些
WEB_CAPABILITIES = {"research.web_search"}

# 显式路径映射（审查文档 §5.3：Adapter 不得自行拼接 capability 作为 URL）。
# 路径由 bdlh-web-search-adapter 的 app.js 路由定义（POST /api/search）。
_WEB_API_PATHS: dict[str, str] = {
    "research.web_search": "/api/search",
}

# bdlh-web-search-adapter 协议固定 schemaVersion（contract.js 强制校验）
_WRAPPER_SCHEMA_VERSION = "1.0"


class HttpWebSearchAdapter:
    """通过 HTTP 调用 bdlh-web-search-adapter 服务的实现。

    服务未配置或调用失败时返回 UNAVAILABLE，永不 mock（实施 Prompt 缺口 G3）。
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float = 20.0,
        *,
        agent_id: str | None = None,
        token: str | None = None,
    ):
        self._base_url = base_url
        self._timeout = timeout_seconds
        self._agent_id = agent_id
        self._token = token

    async def execute(self, capability: str, arguments: dict) -> Observation:
        if capability not in WEB_CAPABILITIES:
            return self._failed_observation(capability, f"web-search 白名单外能力: {capability}")

        if not self._base_url:
            return self._unavailable_observation(capability, "web-search 服务未配置，不允许 mock 降级")

        path = _WEB_API_PATHS.get(capability)
        if path is None:
            return self._failed_observation(capability, f"web-search 无对应契约路径: {capability}")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._agent_id:
            headers["x-agent-id"] = self._agent_id
        if self._token:
            headers["x-search-token"] = self._token

        try:
            body = self._build_request_body(arguments)
        except ValueError as exc:
            return self._failed_observation(capability, str(exc))

        try:
            import httpx

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url.rstrip('/')}{path}",
                    json=body,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                return self._wrap_success(capability, data)
        except Exception as exc:
            logger.warning("web-search 调用失败 (capability=%s): %s", capability, exc)
            return self._unavailable_observation(capability, f"web-search 调用失败: {exc}")

    # ── 请求体构造 ──

    @staticmethod
    def _build_request_body(arguments: dict) -> dict:
        """把统一参数 {query, purpose_code?, max_results?, mode?} 翻译成 wrapper 的 tasks 结构。

        wrapper contract.js 要求：schemaVersion + tasks 数组，每 task 至少有 taskId/query/purposeCode。
        统一层 arguments 是单查询语义，包装成单 task 批量（taskId 用 "default"）。
        """
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("research.web_search 缺少 query 参数")
        task: dict[str, Any] = {
            "taskId": str(arguments.get("task_id", "default")),
            "purposeCode": str(arguments.get("purpose_code", "GENERAL_RESEARCH")),
            "query": query,
        }
        # 可选参数透传（wrapper contract.js 已做范围校验）
        if "max_results" in arguments:
            task["maxResults"] = int(arguments["max_results"])
        if "mode" in arguments:
            task["mode"] = str(arguments["mode"])  # "GENERAL" | "NEWS"
        if "freshness_days" in arguments:
            task["freshnessDays"] = int(arguments["freshness_days"])
        return {"schemaVersion": _WRAPPER_SCHEMA_VERSION, "tasks": [task]}

    def _wrap_success(self, capability: str, data: dict) -> Observation:
        """把 wrapper 响应包装为 Observation。

        wrapper 成功响应信封：{schemaVersion, requestId, provider, results[], errors[]}。
        状态判定（P0-1 空结果降级）：
        - 有结果、无错误 → SUCCESS；
        - 有结果、有错误 → PARTIAL（部分任务失败但仍有结果）；
        - 无结果（errors 含 EMPTY_RESULTS 或全部任务失败）→ PARTIAL，并在
          known_unavailable 标注 capability，禁止伪装成"成功且零结果"——
          否则下游会误判"市场无相关新闻"，把 SearXNG 被反爬当成事实。
        """
        results = data.get("results", [])
        errors = data.get("errors", [])
        has_results = len(results) > 0
        has_errors = len(errors) > 0

        if has_results and not has_errors:
            status = "SUCCESS"
            quality_status = "OK"
            known_unavailable: list[str] = []
        elif has_results and has_errors:
            status = "PARTIAL"
            quality_status = "PARTIAL"
            known_unavailable = []
        else:
            # 无结果：无论 errors 是 EMPTY_RESULTS 还是全任务失败，统一降级，
            # 并在 known_unavailable 显式标注，让 coverage/assemble 能识别"搜了没拿到"。
            status = "PARTIAL"
            quality_status = "PARTIAL"
            known_unavailable = [capability]

        quality = DataQuality(
            completeness=min(1.0, len(results) / max(1, len(results) + len(errors))),
            quality_status=quality_status,
            known_unavailable=known_unavailable,
        )
        return Observation(
            observation_id=str(uuid4()),
            capability=capability,
            status=status,
            data=data,
            data_quality=quality,
            provenance=[
                ProvenanceRecord(
                    source="bdlh-web-search-adapter",
                    tool=capability,
                    request_id=data.get("requestId"),
                    retrieved_at=_now_iso(),
                )
            ],
        )

    # ── 错误 Observation ──

    @staticmethod
    def _failed_observation(capability: str, message: str) -> Observation:
        return Observation(
            observation_id=str(uuid4()),
            capability=capability,
            status="FAILED",
            data=None,
            data_quality=DataQuality(quality_status="INVALID"),
            provenance=[],
            error_code="WEB_SEARCH_UNAVAILABLE",
            error_message=message,
        )

    @staticmethod
    def _unavailable_observation(capability: str, message: str) -> Observation:
        return Observation(
            observation_id=str(uuid4()),
            capability=capability,
            status="UNAVAILABLE",
            data=None,
            data_quality=DataQuality(quality_status="INVALID", known_unavailable=[capability]),
            provenance=[],
            error_code="WEB_SEARCH_UNAVAILABLE",
            error_message=message,
        )


def create_web_search_adapter(
    base_url: str | None = None,
    timeout_seconds: float = 20.0,
    *,
    agent_id: str | None = None,
    token: str | None = None,
    production: bool | None = None,
) -> WebSearchAdapter:
    """工厂函数：创建 HttpWebSearchAdapter。

    ``production`` 参数已废弃（G3）；行为始终 fail-closed，不 mock。
    """
    del production
    return HttpWebSearchAdapter(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        agent_id=agent_id,
        token=token,
    )


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()
