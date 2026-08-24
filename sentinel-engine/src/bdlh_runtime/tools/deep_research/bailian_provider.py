"""百炼联网搜索 Provider（AtomicSearchPort 实现，ADR-016 §7 / §17.3）。

固定链路：``BailianWebSearchProvider → 百炼 WebSearch MCP (streamable HTTP)``。
未配置凭证时返回 UNAVAILABLE；失败时**不得**回落 SearXNG。
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlparse

from bdlh_runtime.tools.deep_research.atomic_search import (
    AtomicSearchBatch,
    AtomicSearchHit,
    AtomicSearchRequest,
)

logger = logging.getLogger("bdlh_runtime.tools.deep_research.bailian")

DEFAULT_BAILIAN_WEB_SEARCH_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/mcp"
BAILIAN_WEB_SEARCH_TOOL = "bailian_web_search"
# ADR-016 §17.3：进程级速率软顶（次 / 分钟）
DEFAULT_RATE_LIMIT_PER_MINUTE = 30


class _McpToolCaller(Protocol):
    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class ProcessRateLimiter:
    """进程内滑动窗口软限流；超限返回 False（由 Provider 映射为 PARTIAL/排队语义）。"""

    def __init__(self, *, max_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE) -> None:
        self._max = max(1, max_per_minute)
        self._timestamps: list[float] = []

    def try_acquire(self) -> bool:
        now = time.monotonic()
        cutoff = now - 60.0
        self._timestamps = [t for t in self._timestamps if t >= cutoff]
        if len(self._timestamps) >= self._max:
            return False
        self._timestamps.append(now)
        return True


_GLOBAL_RATE_LIMITER = ProcessRateLimiter()


class BailianWebSearchProvider:
    """经服务端凭证访问百炼联网搜索 MCP 的原子搜索 Provider。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint: str | None = None,
        timeout_seconds: float = 20.0,
        tool_name: str = BAILIAN_WEB_SEARCH_TOOL,
        mcp_client: _McpToolCaller | None = None,
        rate_limiter: ProcessRateLimiter | None = None,
        rate_limit_per_minute: int | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip() or None
        raw_endpoint = (endpoint or "").strip() or None
        # 仅有 Key 时默认官方 Streamable HTTP 地址（ADR §17.3 中国大陆默认）
        self._endpoint = raw_endpoint or (DEFAULT_BAILIAN_WEB_SEARCH_ENDPOINT if self._api_key else None)
        self._timeout = timeout_seconds
        self._tool_name = tool_name
        self._mcp_client = mcp_client
        if rate_limiter is not None:
            self._rate_limiter = rate_limiter
        elif rate_limit_per_minute is not None:
            self._rate_limiter = ProcessRateLimiter(max_per_minute=rate_limit_per_minute)
        else:
            self._rate_limiter = _GLOBAL_RATE_LIMITER

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._endpoint)

    def _build_client(self) -> _McpToolCaller:
        if self._mcp_client is not None:
            return self._mcp_client
        from bdlh_runtime.integrations.mcp.client import create_mcp_client

        assert self._api_key and self._endpoint
        return create_mcp_client(
            "streamable_http",
            self._endpoint,
            self._timeout,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )

    async def search(self, request: AtomicSearchRequest) -> AtomicSearchBatch:
        if not self.configured:
            return AtomicSearchBatch(
                request_id=request.request_id,
                status="UNAVAILABLE",
                error_code="ATOMIC_SEARCH_UNAVAILABLE",
                error_message="BailianWebSearchProvider is not configured (missing key/endpoint)",
            )

        if not self._rate_limiter.try_acquire():
            return AtomicSearchBatch(
                request_id=request.request_id,
                status="UNAVAILABLE",
                error_code="ATOMIC_SEARCH_RATE_LIMITED",
                error_message="Bailian process soft rate limit exceeded (ADR-016 §17.3)",
            )

        query = " ".join(q.strip() for q in request.queries if q and q.strip())
        if not query:
            return AtomicSearchBatch(
                request_id=request.request_id,
                status="EMPTY",
                hits=[],
                error_code=None,
                error_message="empty queries",
            )

        arguments: dict[str, Any] = {
            "query": query,
            "count": int(request.max_results),
        }
        # 可选域过滤：百炼官方 schema 未必支持；有则附带，解析侧忽略未知字段
        if request.include_domains:
            arguments["include_domains"] = list(request.include_domains)
        if request.exclude_domains:
            arguments["exclude_domains"] = list(request.exclude_domains)

        try:
            client = self._build_client()
            raw = await client.call_tool(self._tool_name, arguments)
        except Exception as exc:  # noqa: BLE001 — Provider 边界统一 UNAVAILABLE
            logger.warning(
                "bailian_mcp_call_failed request_id=%s err=%s",
                request.request_id,
                type(exc).__name__,
            )
            return AtomicSearchBatch(
                request_id=request.request_id,
                status="UNAVAILABLE",
                error_code="ATOMIC_SEARCH_UNAVAILABLE",
                error_message=f"Bailian MCP call failed: {type(exc).__name__}: {exc}",
            )

        if raw.get("is_error"):
            return AtomicSearchBatch(
                request_id=request.request_id,
                status="UNAVAILABLE",
                error_code="ATOMIC_SEARCH_UNAVAILABLE",
                error_message=str(raw.get("text") or "Bailian MCP returned is_error"),
            )

        hits = parse_bailian_search_payload(str(raw.get("text") or ""))
        if not hits:
            return AtomicSearchBatch(
                request_id=request.request_id,
                status="EMPTY",
                hits=[],
            )
        return AtomicSearchBatch(
            request_id=request.request_id,
            status="SUCCESS",
            hits=hits[: request.max_results],
        )


def parse_bailian_search_payload(text: str) -> list[AtomicSearchHit]:
    """把百炼 MCP 文本载荷解析为 AtomicSearchHit（容错多种字段名）。"""

    payload = _coerce_json_payload(text)
    if payload is None:
        return []

    pages = _extract_pages(payload)
    now = datetime.now(UTC).isoformat()
    hits: list[AtomicSearchHit] = []
    seen_urls: set[str] = set()
    for page in pages:
        if not isinstance(page, dict):
            continue
        url = str(page.get("url") or page.get("link") or page.get("href") or page.get("page_url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        title = str(page.get("title") or page.get("name") or url).strip() or url
        summary = str(
            page.get("snippet")
            or page.get("summary")
            or page.get("description")
            or page.get("content")
            or page.get("body")
            or ""
        ).strip()
        summary = sanitize_snippet(summary)
        domain = str(page.get("domain") or page.get("site") or "").strip()
        if not domain:
            domain = urlparse(url).netloc
        published = page.get("published_at") or page.get("publish_time") or page.get("date")
        hits.append(
            AtomicSearchHit(
                title=title[:500],
                url=url[:2000],
                summary=summary[:2000],
                domain=domain[:200],
                published_at=str(published) if published else None,
                retrieved_at=now,
                provider="bailian",
            )
        )
    return hits


def hits_from_dicts(rows: list[dict]) -> list[AtomicSearchHit]:
    """测试辅助：把简单 dict 转成 AtomicSearchHit。"""
    now = datetime.now(UTC).isoformat()
    return [
        AtomicSearchHit(
            title=str(row.get("title") or "untitled"),
            url=str(row.get("url") or ""),
            summary=str(row.get("summary") or ""),
            domain=str(row.get("domain") or ""),
            retrieved_at=str(row.get("retrieved_at") or now),
            provider="bailian",
        )
        for row in rows
    ]


def _coerce_json_payload(text: str) -> Any | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 偶发前后夹杂说明文字：截取首个 JSON 对象/数组
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _extract_pages(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("pages", "results", "items", "data", "webPages", "organic"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = value.get("value") or value.get("pages") or value.get("results")
            if isinstance(nested, list):
                return nested
    return []


_INJECTION_PATTERNS = (
    re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior)\s+instructions?"),
    re.compile(r"(?i)system\s*prompt"),
    re.compile(r"(?i)<\s*(script|iframe)\b"),
)


def sanitize_snippet(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    for pattern in _INJECTION_PATTERNS:
        cleaned = pattern.sub("[filtered]", cleaned)
    return cleaned
