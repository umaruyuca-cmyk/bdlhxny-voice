"""ReAct 停止条件：GoalCoverage 优先于「扫完 allowed」（重写 §6.2）。"""

from __future__ import annotations

import pytest

from bdlh_runtime.contracts.observation import DataQuality, Observation, ProvenanceRecord
from bdlh_runtime.registry import load_and_validate
from bdlh_runtime.runtimes.langgraph.agents.research_agent import (
    LlmResearchAgent,
    RuleBasedResearchAgent,
)
from bdlh_runtime.runtimes.langgraph.graphs.market_data_graph import build_market_data_graph

from tests.registry.seeded_store import build_seeded_store


class FakeGateway:
    def __init__(self, observations: dict[str, Observation]):
        self._obs = observations
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, capability: str, arguments: dict, *, run_id: str = ""):
        self.calls.append((capability, arguments))
        return self._obs[capability]


class FinishEagerLlm:
    """无论 Goal 如何都建议 finish——控制器 / Agent 门闸应拒绝。"""

    def invoke(self, messages):
        class _R:
            content = '{"action": "finish", "arguments": {}, "reason": "eager"}'

        return _R()


def _obs(capability: str) -> Observation:
    return Observation(
        observation_id=f"obs-{capability}",
        capability=capability,
        status="SUCCESS",
        data={"symbol": "600519"},
        data_quality=DataQuality(completeness=1.0, quality_status="OK"),
        provenance=[
            ProvenanceRecord(
                source="fake", tool=capability, retrieved_at="2026-08-06T00:00:00Z"
            )
        ],
    )


def test_llm_finish_with_pending_goal_falls_back_to_rule_agent() -> None:
    """LLM FINISH 但仍有 PENDING Goal → 拒绝结束，降级规则版继续选工具。"""
    agent = LlmResearchAgent(FinishEagerLlm())
    goals = [
        {
            "goal_id": "g1",
            "objective": "报价",
            "status": "PENDING",
            "success_criteria": [
                {
                    "criterion_id": "c1",
                    "description": "quote",
                    "candidate_capabilities": ["market.get_realtime_quote"],
                }
            ],
        }
    ]
    specs = [
        {
            "name": "market.get_realtime_quote",
            "required_arguments": ["symbol"],
            "depends_on": [],
        }
    ]
    action = agent.choose_next_action([], specs, goals=goals)
    assert not action.is_finish
    assert action.action == "market.get_realtime_quote"


def test_rule_agent_does_not_sweep_unrelated_allowed() -> None:
    """有 PENDING Goal 时只追候选，不把整个 allowed 扫一遍。"""
    agent = RuleBasedResearchAgent()
    goals = [
        {
            "goal_id": "g1",
            "objective": "报价",
            "status": "PENDING",
            "success_criteria": [
                {
                    "criterion_id": "c1",
                    "description": "quote",
                    "candidate_capabilities": ["market.get_realtime_quote"],
                }
            ],
        }
    ]
    specs = [
        {"name": "market.get_valuation", "required_arguments": ["symbol"], "depends_on": []},
        {
            "name": "market.get_realtime_quote",
            "required_arguments": ["symbol"],
            "depends_on": [],
        },
        {"name": "market.get_news", "required_arguments": ["symbol"], "depends_on": []},
    ]
    action = agent.choose_next_action([], specs, goals=goals)
    assert action.action == "market.get_realtime_quote"


@pytest.mark.asyncio
async def test_react_stops_when_goals_settled_even_if_allowed_remain() -> None:
    """Goal COVERED 后即使 allowed 还有未尝试能力，ReAct 也应停止。"""
    snapshot = load_and_validate(build_seeded_store())
    gateway = FakeGateway(
        {
            "market.resolve_instrument": _obs("market.resolve_instrument"),
            "market.get_realtime_quote": _obs("market.get_realtime_quote"),
        }
    )
    graph = build_market_data_graph(
        gateway_adapter=gateway,
        research_agent=RuleBasedResearchAgent(),
        registry_snapshot=snapshot,
        max_react_rounds=8,
    )
    state = {
        "run_id": "goal-stop",
        "thread_id": "goal-stop",
        "request": {"message": "600519 现价"},
        "understand": {
            "goals": [
                {
                    "goal_id": "g1",
                    "objective": "现价",
                    "requested_topics": [],
                    "needs_account": False,
                    "needs_profile": False,
                    "status": "PENDING",
                    "observation_refs": [],
                    "success_criteria": [
                        {
                            "criterion_id": "c1",
                            "topic": None,
                            "description": "报价",
                            "candidate_capabilities": [
                                "market.resolve_instrument",
                                "market.get_realtime_quote",
                            ],
                            "observation_refs": [],
                        }
                    ],
                }
            ],
            "entities": {"instruments": ["600519"]},
            "constraints": [],
            "missing": [],
            "needs_external": True,
        },
        "observations": [],
        "allowed": [
            "market.resolve_instrument",
            "market.get_realtime_quote",
            "market.get_valuation",
            "market.get_news",
            "research.web_search",
        ],
        "capability_candidates": [
            {"name": "market.resolve_instrument", "required_arguments": ["symbol"], "depends_on": []},
            {
                "name": "market.get_realtime_quote",
                "required_arguments": ["symbol"],
                "depends_on": ["market.resolve_instrument"],
            },
            {"name": "market.get_valuation", "required_arguments": ["symbol"], "depends_on": []},
            {"name": "market.get_news", "required_arguments": ["symbol"], "depends_on": []},
            {"name": "research.web_search", "required_arguments": ["query"], "depends_on": []},
        ],
        "budget": {"react_round_limit": 8, "tool_call_limit": 12},
        "workflow_plan": {
            "plan_id": "p",
            "tasks": [
                {
                    "task_id": "market_data",
                    "task_type": "market_data",
                    "depends_on": [],
                    "status": "PENDING",
                    "input_ref": [],
                    "output_ref": [],
                }
            ],
        },
        "current_task_id": "market_data",
        "events": [],
    }
    result = await graph.ainvoke(state)
    called = [name for name, _ in gateway.calls]
    assert "market.get_realtime_quote" in called
    assert "market.get_valuation" not in called
    assert "market.get_news" not in called
    assert "research.web_search" not in called
    goals = (result.get("understand") or {}).get("goals") or []
    assert goals and goals[0].get("status") == "COVERED"
