"""Market Data Graph 真实 ReAct 模式回归测试（P0 验收）。

验证审查文档 §3.1 的验收标准：
- Fake Gateway 注入 → select_action → execute_tool → normalize_observation
  → evaluate_market_data → 子图结束；
- action / pending observation / round counter 在节点间正确传递；
- 不得出现 GraphRecursionError。
"""

from __future__ import annotations

import pytest

from bdlh_runtime.contracts.observation import DataQuality, Observation, ProvenanceRecord
from bdlh_runtime.runtimes.langgraph.graphs.market_data_graph import build_market_data_graph


class FakeGateway:
    """模拟 Gateway：按 capability 返回固定 Observation。"""

    def __init__(self, observations: dict[str, Observation]):
        self._obs = observations
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, capability: str, arguments: dict, *, run_id: str = ""):
        self.calls.append((capability, arguments))
        obs = self._obs.get(capability)
        if obs is None:
            return Observation(
                observation_id="f-1",
                capability=capability,
                status="FAILED",
                data=None,
                data_quality=DataQuality(quality_status="INVALID"),
                error_code="NOT_FOUND",
            )
        return obs


class FakeResearchAgent:
    """模拟 Research Agent：依次返回固定动作序列，最后 finish。"""

    def __init__(self, actions: list[str]):
        self._actions = list(actions)

    def choose_next_action(self, observations, remaining_requirements):
        from bdlh_runtime.runtimes.langgraph.agents.research_agent import ResearchAction

        if self._actions:
            action = self._actions.pop(0)
            return ResearchAction(action=action, arguments={"symbol": "600519"}, reason="test")
        return ResearchAction(action="finish", arguments={}, reason="done")


def _observation(capability: str) -> Observation:
    """构造一个成功的 Observation。"""
    return Observation(
        observation_id=f"obs-{capability}",
        capability=capability,
        status="SUCCESS",
        data={"symbol": "600519", "price": 1300.0},
        data_quality=DataQuality(completeness=1.0, quality_status="OK"),
        provenance=[ProvenanceRecord(source="fake-gateway", tool=capability, retrieved_at="2026-08-06T00:00:00Z")],
    )


def _initial_state(capabilities: list[dict]) -> dict:
    """构造最小输入状态（重写：allowed + 窗口 specs + workflow_plan）。"""
    names = [item["capability"] for item in capabilities]
    return {
        "run_id": "test-react",
        "thread_id": "test-react",
        "request": {"message": "分析 600519"},
        "understand": {"entities": {"instruments": ["600519"]}},
        "observations": [],
        "allowed": names,
        "capability_candidates": [
            {"name": name, "required_arguments": ["symbol"], "depends_on": []}
            for name in names
        ],
        "budget": {"react_round_limit": 6, "tool_call_limit": 10},
        # evaluate_market_data 会调用 _complete_current_task，需要有效 plan
        "workflow_plan": {
            "plan_id": "test-plan",
            "tasks": [
                {"task_id": "market_data", "task_type": "market_data", "depends_on": [], "status": "PENDING", "input_ref": [], "output_ref": []},
            ],
        },
        "current_task_id": "market_data",
        "events": [],
    }


@pytest.mark.asyncio
async def test_react_loop_completes_with_fake_gateway():
    """Fake Gateway + 3 个动作 → 子图正常结束，不触发 GraphRecursionError。"""
    gateway = FakeGateway(
        {
            "market.get_realtime_quote": _observation("market.get_realtime_quote"),
            "market.get_historical_prices": _observation("market.get_historical_prices"),
            "market.get_financial_statements": _observation("market.get_financial_statements"),
        }
    )
    agent = FakeResearchAgent(
        [
            "market.get_realtime_quote",
            "market.get_historical_prices",
            "market.get_financial_statements",
        ]
    )
    graph = build_market_data_graph(gateway_adapter=gateway, research_agent=agent, max_react_rounds=6)

    requirements = [
        {"capability": "market.get_realtime_quote", "arguments": {"symbol": "600519"}},
        {"capability": "market.get_historical_prices", "arguments": {"symbol": "600519"}},
        {"capability": "market.get_financial_statements", "arguments": {"symbol": "600519"}},
    ]
    result = await graph.ainvoke(_initial_state(requirements))

    # 3 个能力都执行了
    assert gateway.calls == [
        ("market.get_realtime_quote", {"symbol": "600519"}),
        ("market.get_historical_prices", {"symbol": "600519"}),
        ("market.get_financial_statements", {"symbol": "600519"}),
    ]
    # 3 个 Observation 都进了 state
    capabilities = {o["capability"] for o in result["observations"]}
    assert capabilities == {
        "market.get_realtime_quote",
        "market.get_historical_prices",
        "market.get_financial_statements",
    }
    # ReAct 轮次 = 3（3 个动作）
    assert result["_react_round"] == 3


@pytest.mark.asyncio
async def test_react_loop_stops_at_round_limit():
    """动作数超过 max_react_rounds 时，子图在上限处停止而非无限循环。"""
    gateway = FakeGateway({"market.get_realtime_quote": _observation("market.get_realtime_quote")})
    # 10 个动作但上限 3
    agent = FakeResearchAgent(["market.get_realtime_quote"] * 10)
    graph = build_market_data_graph(gateway_adapter=gateway, research_agent=agent, max_react_rounds=3)

    requirements = [{"capability": "market.get_realtime_quote", "arguments": {"symbol": "600519"}}]
    result = await graph.ainvoke(_initial_state(requirements))

    # 不超过上限
    assert result["_react_round"] <= 3
    assert len(gateway.calls) <= 3
    # 正常结束（走到了 evaluate_market_data 或后续，无递归异常）
    assert "observations" in result


@pytest.mark.asyncio
async def test_react_finish_action_ends_immediately():
    """Agent 直接返回 finish → 不执行任何工具，直接到 evaluate。"""
    gateway = FakeGateway({})
    agent = FakeResearchAgent([])  # 无动作 → 直接 finish
    graph = build_market_data_graph(gateway_adapter=gateway, research_agent=agent, max_react_rounds=6)

    result = await graph.ainvoke(_initial_state([]))
    assert gateway.calls == []
    assert result["_react_round"] == 0


@pytest.mark.asyncio
async def test_react_loop_with_memory_store_no_interference():
    """有记忆注入时 ReAct 循环正常工作（验证记忆不污染子图内部状态）。"""
    gateway = FakeGateway({"market.get_realtime_quote": _observation("market.get_realtime_quote")})
    agent = FakeResearchAgent(["market.get_realtime_quote"])
    graph = build_market_data_graph(gateway_adapter=gateway, research_agent=agent, max_react_rounds=6)

    state = _initial_state([{"capability": "market.get_realtime_quote", "arguments": {"symbol": "600519"}}])
    state["user_id"] = "u1"
    state["recalled_memories"] = [{"content": "用户偏好白酒"}]
    state["user_profile"] = {"risk_tolerance": "moderate"}

    result = await graph.ainvoke(state)
    assert len(gateway.calls) == 1
    assert result["_react_round"] == 1


@pytest.mark.asyncio
async def test_async_nodes_supported():
    """异步节点（execute_tool 是 async）在子图中可正常运行。"""
    gateway = FakeGateway({"market.get_realtime_quote": _observation("market.get_realtime_quote")})
    agent = FakeResearchAgent(["market.get_realtime_quote"])
    graph = build_market_data_graph(gateway_adapter=gateway, research_agent=agent, max_react_rounds=6)

    state = _initial_state([{"capability": "market.get_realtime_quote", "arguments": {"symbol": "600519"}}])
    result = await graph.ainvoke(state)
    assert result["_react_round"] == 1
    assert gateway.calls[0][0] == "market.get_realtime_quote"


@pytest.mark.asyncio
async def test_quote_only_window_executes_single_capability():
    """重写语义：窗口仅剩 quote（resolve 已满足）→ 规则版一步执行 quote。"""
    from bdlh_runtime.runtimes.langgraph.agents.research_agent import RuleBasedResearchAgent

    gateway = FakeGateway({"market.get_realtime_quote": _observation("market.get_realtime_quote")})

    graph = build_market_data_graph(
        gateway_adapter=gateway,
        research_agent=RuleBasedResearchAgent(),
    )
    state = _initial_state(
        [{"capability": "market.get_realtime_quote", "arguments": {"symbol": "600519"}}]
    )
    # resolve 已在前序完成（observation 存在），quote 是窗口内唯一未执行能力
    state["observations"] = [{
        "observation_id": "obs-resolve",
        "capability": "market.resolve_instrument",
        "status": "SUCCESS",
        "data": {"symbol": "600519"},
        "data_quality": {"completeness": 1.0, "quality_status": "OK"},
        "provenance": [],
    }]

    result = await graph.ainvoke(state)

    assert gateway.calls == [("market.get_realtime_quote", {"symbol": None})]
    assert {item["capability"] for item in result["observations"]} == {
        "market.resolve_instrument",
        "market.get_realtime_quote",
    }
    assert result["tool_calls_used"] == 1


@pytest.mark.asyncio
async def test_tool_call_budget_stops_react_before_gateway_call():
    """达到工具调用预算时返回结构化失败 Observation，而不是继续调用外部服务。"""

    gateway = FakeGateway({"market.get_realtime_quote": _observation("market.get_realtime_quote")})
    agent = FakeResearchAgent(["market.get_realtime_quote"])
    graph = build_market_data_graph(gateway_adapter=gateway, research_agent=agent)
    state = _initial_state(
        [{"capability": "market.get_realtime_quote", "arguments": {"symbol": "600519"}}]
    )
    state["budget"] = {"react_round_limit": 4, "tool_call_limit": 0}
    state["tool_calls_used"] = 0

    result = await graph.ainvoke(state)

    assert gateway.calls == []
    assert result["budget_exhausted"] is True
    assert result["observations"][0]["error_code"] == "BUDGET_EXCEEDED"
