"""research.* 路由不得把 deep_search 丢进浅搜 Adapter；调用策略可降级。"""

from __future__ import annotations

import pytest

from bdlh_runtime.runtimes.langgraph.graphs.market_data_graph import (
    _fill_action_arguments,
    _make_execute_tool_node,
)
from bdlh_runtime.tools.deep_research import (
    DEEP_SEARCH_CAPABILITY,
    DeepResearchToolExecutor,
    WEB_SEARCH_CAPABILITY,
    apply_deep_call_policy_to_action,
)
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
        "request": {"text": "请做深度调研并交叉验证舆情与风险"},
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


def test_fill_deep_search_arguments_from_user_text():
    state = {
        "run_id": "run-42",
        "request": {"text": "请深度调研茅台舆情并交叉验证"},
    }
    args = _fill_action_arguments(
        {"action": DEEP_SEARCH_CAPABILITY, "arguments": {}},
        state,
    )
    assert args["request_id"] == "run-42"
    assert "深度调研" in args["question"] or "茅台" in args["question"]
    assert args["objective"]
    assert args["research_topics"] == []


def test_call_policy_downgrades_deep_without_trigger():
    action = apply_deep_call_policy_to_action(
        {"action": DEEP_SEARCH_CAPABILITY, "arguments": {}, "reason": "llm"},
        {"run_id": "r1", "request": {"text": "茅台现在股价多少"}},
        allowed={DEEP_SEARCH_CAPABILITY, WEB_SEARCH_CAPABILITY},
    )
    assert action["action"] == WEB_SEARCH_CAPABILITY
    assert "downgrade_web_search" in action["reason"]


def test_call_policy_keeps_deep_when_triggered():
    action = apply_deep_call_policy_to_action(
        {
            "action": DEEP_SEARCH_CAPABILITY,
            "arguments": {
                "research_topics": ["舆情", "风险"],
                "success_criteria": ["有舆情来源", "有风险来源"],
            },
            "reason": "llm",
        },
        {"run_id": "r1", "request": {"text": "请做深度调研并交叉验证"}},
        allowed={DEEP_SEARCH_CAPABILITY, WEB_SEARCH_CAPABILITY},
    )
    assert action["action"] == DEEP_SEARCH_CAPABILITY
    assert action["deep_trigger_reasons"]
