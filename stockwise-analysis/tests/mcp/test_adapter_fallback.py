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
from stockwise_analysis.observations.normalizer import ObservationNormalizer


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
async def test_text_wrapped_tool_error_triggers_fallback():
    """MCP 将工具错误包装成普通文本且 isError=false 时仍应触发 fallback。"""
    primary = FakeClient({
        "get_realtime_data": {
            "text": "Error calling tool 'get_realtime_data': upstream token expired",
            "is_error": False,
        }
    })
    fallback = FakeClient({"get_realtime_quote": {"text": '[{"price": 1302.0}]', "is_error": False}})
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


@pytest.mark.asyncio
async def test_financial_statements_fans_out_to_three_primary_tools():
    """一个统一财报能力应并行取得资产负债表、利润表和现金流量表。"""
    akshare = FakeClient({})
    cn_financial = FakeClient({
        "get_balance_sheet": {"text": '[{"报告期":"2026Q2","资产":1}]', "is_error": False},
        "get_income_statement": {"text": '[{"报告期":"2026Q2","营业收入":2}]', "is_error": False},
        "get_cash_flow_statement": {"text": '[{"报告期":"2026Q2","经营现金流":3}]', "is_error": False},
    })
    adapter = McpGatewayAdapter(_clients(akshare, cn_financial))

    observation = await adapter.execute("market.get_financial_statements", {"symbol": "600519"})
    normalized = ObservationNormalizer().normalize(observation)

    assert observation.status == "SUCCESS"
    assert set(cn_financial.calls) == {
        "get_balance_sheet",
        "get_income_statement",
        "get_cash_flow_statement",
    }
    assert akshare.calls == []
    assert normalized.data["available_statements"] == [
        "balance_sheet",
        "cash_flow_statement",
        "income_statement",
    ]


@pytest.mark.asyncio
async def test_financial_statements_preserve_partial_data_when_one_statement_fails():
    """单张报表主备均失败时保留其余报表，并把统一能力标为 PARTIAL。"""
    akshare = FakeClient({
        "get_cash_flow": {"text": '{"error":true,"message":"fallback failed"}', "is_error": False},
    })
    cn_financial = FakeClient({
        "get_balance_sheet": {"text": '[{"报告期":"2026Q2","资产":1}]', "is_error": False},
        "get_income_statement": {"text": '[{"报告期":"2026Q2","营业收入":2}]', "is_error": False},
        "get_cash_flow_statement": {"text": '{"error":true,"message":"primary failed"}', "is_error": False},
    })
    adapter = McpGatewayAdapter(_clients(akshare, cn_financial))

    observation = await adapter.execute("market.get_financial_statements", {"symbol": "600519"})
    normalized = ObservationNormalizer().normalize(observation)

    assert observation.status == "PARTIAL"
    assert "financial.cash_flow_statement" in observation.data_quality.known_unavailable
    assert normalized.status == "PARTIAL"
    assert normalized.data["available_statements"] == ["balance_sheet", "income_statement"]
