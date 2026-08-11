"""MCP Adapter fallback 测试（审查文档 §4.2 / §8.1）。

验证：
- 网络异常 → fallback；
- 协议错误 isError=true → fallback（审查重点）；
- 服务端吞错 {"error":true} → fallback（审查重点）；
- 主备均失败 → 写入 known_unavailable。
"""

from __future__ import annotations

import pytest

from stockwise_analysis.integrations.mcp.adapter import McpGatewayAdapter


class FakeClient:
    """模拟 MCP Client，按 tool 名返回预设响应。"""

    def __init__(self, responses: dict[str, dict] | None = None, raises: dict[str, Exception] | None = None):
        self._responses = responses or {}
        self._raises = raises or {}
        self.calls: list[str] = []

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        self.calls.append(tool_name)
        if tool_name in self._raises:
            raise self._raises[tool_name]
        return self._responses.get(tool_name, {"text": "[]", "is_error": False})


def _clients(primary: FakeClient, fallback: FakeClient) -> dict:
    """构造 client 字典（路由表按 mcp 名索引）。"""
    return {"akshare-one-mcp": primary, "cn-financial-mcp": fallback}


@pytest.mark.asyncio
async def test_protocol_error_triggers_fallback():
    """首选协议错误（isError=true）→ 触发 fallback。"""
    primary = FakeClient({"get_realtime_data": {"text": "工具内部错误", "is_error": True}})
    fallback = FakeClient({"get_realtime_quote": {"text": '[{"price": 1300.0}]', "is_error": False}})
    adapter = McpGatewayAdapter(_clients(primary, fallback))

    obs = await adapter.execute("market.get_realtime_quote", {"symbol": "600519"})
    assert obs.status == "SUCCESS"
    # fallback 被调用，且溯源标记 fallback_used=True
    assert fallback.calls == ["get_realtime_quote"]
    assert obs.provenance[0].fallback_used is True


@pytest.mark.asyncio
async def test_swallowed_error_triggers_fallback():
    """首选服务端吞错（{"error":true} 且 isError=false）→ 触发 fallback。"""
    primary = FakeClient({"get_realtime_data": {"text": '{"error": true, "message": "RemoteDisconnected"}', "is_error": False}})
    fallback = FakeClient({"get_realtime_quote": {"text": '[{"price": 1301.5}]', "is_error": False}})
    adapter = McpGatewayAdapter(_clients(primary, fallback))

    obs = await adapter.execute("market.get_realtime_quote", {"symbol": "600519"})
    assert obs.status == "SUCCESS"
    assert fallback.calls == ["get_realtime_quote"]
    assert obs.provenance[0].fallback_used is True


@pytest.mark.asyncio
async def test_network_error_triggers_fallback():
    """首选网络异常 → 触发 fallback。"""
    primary = FakeClient(raises={"get_realtime_data": ConnectionError("connection aborted")})
    fallback = FakeClient({"get_realtime_quote": {"text": '[{"price": 1299.0}]', "is_error": False}})
    adapter = McpGatewayAdapter(_clients(primary, fallback))

    obs = await adapter.execute("market.get_realtime_quote", {"symbol": "600519"})
    assert obs.status == "SUCCESS"
    assert fallback.calls == ["get_realtime_quote"]


@pytest.mark.asyncio
async def test_both_fail_writes_known_unavailable():
    """主备均失败 → known_unavailable 标记该能力，状态 FAILED。"""
    primary = FakeClient(raises={"get_realtime_data": ConnectionError("fail")})
    fallback = FakeClient({"get_realtime_quote": {"text": '{"error": true, "message": "也失败"}', "is_error": False}})
    adapter = McpGatewayAdapter(_clients(primary, fallback))

    obs = await adapter.execute("market.get_realtime_quote", {"symbol": "600519"})
    assert obs.status == "FAILED"
    assert obs.error_code == "MCP_UNAVAILABLE"
    assert "market.get_realtime_quote" in obs.data_quality.known_unavailable


@pytest.mark.asyncio
async def test_primary_success_no_fallback():
    """首选成功 → 不触发 fallback。"""
    primary = FakeClient({"get_realtime_data": {"text": '[{"price": 1300.0}]', "is_error": False}})
    fallback = FakeClient({})
    adapter = McpGatewayAdapter(_clients(primary, fallback))

    obs = await adapter.execute("market.get_realtime_quote", {"symbol": "600519"})
    assert obs.status == "SUCCESS"
    assert fallback.calls == []
    assert obs.provenance[0].fallback_used is False
    # source 参数被正确注入
    assert primary.calls == ["get_realtime_data"]


@pytest.mark.asyncio
async def test_unregistered_capability_fails():
    """未注册能力 → 直接 FAILED，不尝试任何 client。"""
    primary = FakeClient({})
    fallback = FakeClient({})
    adapter = McpGatewayAdapter(_clients(primary, fallback))

    obs = await adapter.execute("market.nonexistent", {})
    assert obs.status == "FAILED"
    assert primary.calls == []
    assert fallback.calls == []
