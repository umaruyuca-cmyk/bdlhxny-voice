"""web-search-wrapper 适配器。

网络搜索必须经由 web-search-wrapper 服务读取（架构文档 v3.1 §13.4）：
Python 不允许绕过 wrapper 直接调用 SearXNG 或搜索引擎。

设计原则（与 Java adapter、MCP adapter 一致）：
- 统一能力 research.web_search → web-search-wrapper HTTP API 的翻译在 Adapter 内完成；
- wrapper 返回结果转换为 Observation，不允许 Graph 节点直接拼接搜索 JSON；
- 降级：wrapper 服务不可用（未部署/超时）时返回 mock 搜索结果，保证开发环境
  和测试可跑通完整流程。mock 数据带 is_mock 标记，不伪装成真实搜索结果。

与 Java adapter 的差异（web-search-wrapper 接口特性）：
- 鉴权：双 header（x-agent-id + x-search-token）而非 Bearer；
- 请求体：批量 tasks 结构 {schemaVersion, tasks:[{taskId, query, ...}]}，
  需把统一参数 {query} 包装成 tasks；
- 超时：20s（wrapper 内部已有 10s 上游超时，外层给余量）。
"""

from __future__ import annotations

import logging
from typing import Any, Protocol
from uuid import uuid4

from stockwise_analysis.contracts.observation import DataQuality, Observation, ProvenanceRecord

logger = logging.getLogger("stockwise_analysis.tools.web_search")


class WebSearchAdapter(Protocol):
    """网络搜索必须经由 web-search-wrapper 服务。"""

    async def execute(self, capability: str, arguments: dict) -> Observation:
        """调用白名单 web-search API 并转换为 Observation。"""


# web-search 白名单能力，Adapter 只允许这些
WEB_CAPABILITIES = {"research.web_search"}

# 显式路径映射（审查文档 §5.3：Adapter 不得自行拼接 capability 作为 URL）。
# 路径由 web-search-wrapper 的 app.js 路由定义（POST /api/search）。
_WEB_API_PATHS: dict[str, str] = {
    "research.web_search": "/api/search",
}

# web-search-wrapper 协议固定 schemaVersion（contract.js 强制校验）
_WRAPPER_SCHEMA_VERSION = "1.0"


class HttpWebSearchAdapter:
    """通过 HTTP 调用 web-search-wrapper 服务的实现。

    降级策略（与 Java adapter 一致）：
    - 开发环境（production=False）：服务未配置或调用失败时，降级为
      mock 搜索结果（带 is_mock 标记），保证开发/测试可跑通完整流程；
    - 生产环境（production=True）：**禁止 mock 降级**——服务不可用时返回
      UNAVAILABLE 状态，宁可如实标记不可用也不伪造搜索结论。
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float = 20.0,
        *,
        production: bool = False,
        agent_id: str | None = None,
        token: str | None = None,
    ):
        """base_url 为 wrapper 根地址（如 http://web-search-wrapper:3002）；None 时开发环境走 mock 降级。"""
        self._base_url = base_url
        self._timeout = timeout_seconds
        self._production = production
        self._agent_id = agent_id
        self._token = token

    async def execute(self, capability: str, arguments: dict) -> Observation:
        if capability not in WEB_CAPABILITIES:
            return self._failed_observation(capability, f"web-search 白名单外能力: {capability}")

        # wrapper 服务未配置 → 开发环境 mock 降级，生产环境 UNAVAILABLE
        if not self._base_url:
            if self._production:
                return self._unavailable_observation(capability, "web-search 服务未配置，生产环境不允许 mock 降级")
            return self._mock_observation(capability, arguments)

        # 真实调用 wrapper API（显式路径映射，不拼 capability）
        path = _WEB_API_PATHS.get(capability)
        if path is None:
            return self._failed_observation(capability, f"web-search 无对应契约路径: {capability}")

        # 鉴权 header（双 header，非 Bearer；wrapper auth.js 用 timingSafeEqual 校验）
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._agent_id:
            headers["x-agent-id"] = self._agent_id
        if self._token:
            headers["x-search-token"] = self._token

        # 把统一参数翻译成 wrapper 的 tasks 批量结构（contract.js 校验）
        body = self._build_request_body(arguments)

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
            # 生产环境：不降级 mock，返回 UNAVAILABLE（如实标记）
            if self._production:
                return self._unavailable_observation(capability, f"web-search 调用失败: {exc}")
            return self._mock_observation(capability, arguments)

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
        如果 errors 非空，标记 PARTIAL（部分任务失败但仍有结果）。
        """
        results = data.get("results", [])
        errors = data.get("errors", [])
        status = "PARTIAL" if errors and len(results) > 0 else "SUCCESS"
        quality = DataQuality(
            completeness=min(1.0, len(results) / max(1, len(results) + len(errors))),
            quality_status="OK" if not errors else "PARTIAL",
        )
        return Observation(
            observation_id=str(uuid4()),
            capability=capability,
            status=status,
            data=data,
            data_quality=quality,
            provenance=[ProvenanceRecord(
                source="web-search-wrapper",
                tool=capability,
                request_id=data.get("requestId"),
                retrieved_at=_now_iso(),
            )],
        )

    # ── mock 降级实现（开发环境/测试用，带 is_mock 标记）──

    @staticmethod
    def _mock_observation(capability: str, arguments: dict) -> Observation:
        """mock 搜索结果，确定性，测试用。"""
        query = arguments.get("query", "")
        mock_data = {
            "schemaVersion": _WRAPPER_SCHEMA_VERSION,
            "requestId": "mock-request",
            "provider": "mock",
            "results": [
                {
                    "resultId": "mock-result-1",
                    "taskId": "default",
                    "purposeCode": "MOCK",
                    "title": f"[mock] 与「{query}」相关的示例结果",
                    "url": "https://example.com/mock",
                    "domain": "example.com",
                    "snippet": "这是开发环境降级返回的 mock 搜索结果，不代表真实搜索内容。",
                    "sourceType": "WEB",
                    "provider": "mock",
                    "publishedAt": None,
                    "retrievedAt": _now_iso(),
                    "relevanceScore": 1.0,
                    "is_mock": True,
                }
            ],
            "errors": [],
            "is_mock": True,
        }
        return Observation(
            observation_id=str(uuid4()),
            capability=capability,
            status="SUCCESS",
            data=mock_data,
            data_quality=DataQuality(completeness=0.6, quality_status="PARTIAL"),  # mock 数据标记 PARTIAL
            provenance=[ProvenanceRecord(source="mock-web-search", tool=capability, retrieved_at=_now_iso())],
        )

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
        """生产环境服务不可用：UNAVAILABLE 状态，明确无数据。"""
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
    production: bool = False,
    agent_id: str | None = None,
    token: str | None = None,
) -> WebSearchAdapter:
    """工厂函数：创建 HttpWebSearchAdapter。

    base_url 来自配置 WEB_SEARCH_BASE_URL；未配置时开发环境自动 mock 降级，
    生产环境返回 UNAVAILABLE（不伪造搜索结果）。
    """
    return HttpWebSearchAdapter(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        production=production,
        agent_id=agent_id,
        token=token,
    )


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
