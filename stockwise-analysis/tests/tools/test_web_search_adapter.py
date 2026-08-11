"""web-search 适配器测试（对照 java_data_adapter 测试风格）。

覆盖：mock 降级 / 白名单外拒绝 / 成功包装 Observation / httpx 失败降级 /
生产环境不 mock / 请求体构造。
"""

from __future__ import annotations

import pytest

from stockwise_analysis.tools.web_search_adapter import (
    HttpWebSearchAdapter,
    create_web_search_adapter,
)


# ── mock 降级（开发环境，base_url 未配置）──


async def test_mock_fallback_when_base_url_none_dev():
    """开发环境 base_url=None → mock 降级，返回带 is_mock 的结果。"""
    adapter = create_web_search_adapter(base_url=None, production=False)
    obs = await adapter.execute("research.web_search", {"query": "茅台"})
    assert obs.status == "SUCCESS"
    assert obs.data["is_mock"] is True
    assert obs.data["results"][0]["is_mock"] is True
    assert "茅台" in obs.data["results"][0]["title"]
    assert obs.data_quality.quality_status == "PARTIAL"  # mock 标记 PARTIAL
    assert obs.provenance[0].source == "mock-web-search"


async def test_production_returns_unavailable_when_base_url_none():
    """生产环境 base_url=None → UNAVAILABLE，不伪造。"""
    adapter = create_web_search_adapter(base_url=None, production=True)
    obs = await adapter.execute("research.web_search", {"query": "茅台"})
    assert obs.status == "UNAVAILABLE"
    assert obs.data is None
    assert "research.web_search" in obs.data_quality.known_unavailable
    assert obs.error_code == "WEB_SEARCH_UNAVAILABLE"


# ── 白名单外能力拒绝 ──


async def test_rejects_capability_outside_whitelist():
    adapter = create_web_search_adapter(base_url="http://example.com", production=False)
    obs = await adapter.execute("market.get_realtime_quote", {})
    assert obs.status == "FAILED"
    assert "白名单外" in (obs.error_message or "")


# ── 请求体构造 ──


def test_build_request_body_wraps_query_into_tasks():
    body = HttpWebSearchAdapter._build_request_body({"query": "A股市场", "max_results": 3})
    assert body["schemaVersion"] == "1.0"
    assert len(body["tasks"]) == 1
    assert body["tasks"][0]["query"] == "A股市场"
    assert body["tasks"][0]["maxResults"] == 3
    assert body["tasks"][0]["purposeCode"]  # 有默认值


def test_build_request_body_raises_on_empty_query():
    with pytest.raises(ValueError, match="query"):
        HttpWebSearchAdapter._build_request_body({"query": ""})


# ── 成功包装（mock httpx 响应）──


async def test_success_wraps_observation(monkeypatch):
    """模拟 httpx 返回成功响应，验证 Observation 包装。"""
    adapter = HttpWebSearchAdapter(
        base_url="http://example.com",
        production=False,
        agent_id="test-agent",
        token="x" * 32,
    )

    # mock httpx.AsyncClient
    class MockResponse:
        def raise_for_status(self): pass
        def json(self):
            return {
                "schemaVersion": "1.0",
                "requestId": "req-123",
                "provider": "searxng",
                "results": [
                    {"title": "茅台最新动态", "url": "https://finance.example.com/maotai",
                     "domain": "finance.example.com", "snippet": "茅台发布三季报...",
                     "publishedAt": "2026-08-01T00:00:00Z", "relevanceScore": 0.95},
                ],
                "errors": [],
            }

    class MockClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, json=None, headers=None):
            assert "x-agent-id" in headers
            assert "x-search-token" in headers
            return MockResponse()

    import stockwise_analysis.tools.web_search_adapter as mod
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", MockClient)

    obs = await adapter.execute("research.web_search", {"query": "茅台"})
    assert obs.status == "SUCCESS"
    assert obs.data["results"][0]["title"] == "茅台最新动态"
    assert obs.provenance[0].source == "web-search-wrapper"
    assert obs.provenance[0].request_id == "req-123"


async def test_partial_status_when_errors_present(monkeypatch):
    """wrapper 返回 errors 非空但有结果 → PARTIAL 状态。"""
    adapter = HttpWebSearchAdapter(base_url="http://example.com", production=False)

    class MockResponse:
        def raise_for_status(self): pass
        def json(self):
            return {
                "results": [{"title": "结果1", "url": "https://a.com"}],
                "errors": [{"taskId": "default", "code": "RATE_LIMITED"}],
            }

    class MockClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, json=None, headers=None): return MockResponse()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", MockClient)

    obs = await adapter.execute("research.web_search", {"query": "test"})
    assert obs.status == "PARTIAL"


# ── httpx 失败降级 ──


async def test_httpx_failure_fallback_to_mock_in_dev(monkeypatch):
    """开发环境 httpx 异常 → mock 降级。"""
    adapter = HttpWebSearchAdapter(base_url="http://example.com", production=False)

    class FailingClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): raise ConnectionError("network down")

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", FailingClient)

    obs = await adapter.execute("research.web_search", {"query": "test"})
    assert obs.status == "SUCCESS"
    assert obs.data["is_mock"] is True  # 开发环境降级到 mock


async def test_httpx_failure_returns_unavailable_in_production(monkeypatch):
    """生产环境 httpx 异常 → UNAVAILABLE，不 mock。"""
    adapter = HttpWebSearchAdapter(base_url="http://example.com", production=True)

    class FailingClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): raise ConnectionError("network down")

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", FailingClient)

    obs = await adapter.execute("research.web_search", {"query": "test"})
    assert obs.status == "UNAVAILABLE"
    assert obs.error_code == "WEB_SEARCH_UNAVAILABLE"
