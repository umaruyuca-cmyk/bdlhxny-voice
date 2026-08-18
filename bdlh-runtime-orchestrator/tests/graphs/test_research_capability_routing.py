"""research.* 路由不得把 deep_search 丢进浅搜 Adapter。"""

from __future__ import annotations

import pytest

from bdlh_runtime.runtimes.langgraph.graphs.market_data_graph import _make_execute_tool_node
from bdlh_runtime.tools.deep_research import DEEP_SEARCH_CAPABILITY, DeepResearchToolExecutor
from bdlh_runtime.tools.web_search_adapter import WEB_CAPABILITIES, create_web_search_adapter


class _RecordingGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, capability: str, arguments: dict, *, run_id: str = ""):
        self.calls.append(capability)
        raise AssertionError("gateway should not receive research.deep_search")


@pytest.mark.asyncio
async def test_web_search_adapter_rejects_deep_capability():
    adapter = create_web_search_adapter(base_url=None, production=False)
    obs = await adapter.execute(DEEP_SEARCH_CAPABILITY, {"query": "x"})
    assert obs.status == "FAILED"
    assert DEEP_SEARCH_CAPABILITY not in WEB_CAPABILITIES


@pytest.mark.asyncio
async def test_execute_tool_routes_deep_to_executor_not_web():
    gateway = _RecordingGateway()
    web = create_web_search_adapter(base_url=None, production=False)
    deep = DeepResearchToolExecutor(enabled=False)
    node = _make_execute_tool_node(gateway, web, None, deep)
    state = {
        "run_id": "r1",
        "allowed": [DEEP_SEARCH_CAPABILITY],
        "tool_calls_used": 0,
        "budget": {"tool_call_limit": 10},
        "_current_action": {"action": DEEP_SEARCH_CAPABILITY, "arguments": {}},
        "events": [],
    }
    result = await node(state)
    pending = result["_pending_observation"]
    assert pending["capability"] == DEEP_SEARCH_CAPABILITY
    assert pending["status"] == "UNAVAILABLE"
    assert pending["error_code"] == "DEEP_RESEARCH_NOT_ENABLED"
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_execute_tool_web_search_still_uses_web_adapter():
    gateway = _RecordingGateway()
    web = create_web_search_adapter(base_url=None, production=False)
    node = _make_execute_tool_node(gateway, web, None, DeepResearchToolExecutor(enabled=False))
    state = {
        "run_id": "r1",
        "allowed": ["research.web_search"],
        "tool_calls_used": 0,
        "budget": {"tool_call_limit": 10},
        "_current_action": {"action": "research.web_search", "arguments": {"query": "茅台"}},
        "events": [],
    }
    result = await node(state)
    pending = result["_pending_observation"]
    assert pending["capability"] == "research.web_search"
    assert pending["status"] in {"SUCCESS", "PARTIAL"}
