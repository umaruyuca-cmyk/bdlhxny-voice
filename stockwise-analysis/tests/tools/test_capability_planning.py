from __future__ import annotations

import json

from stockwise_analysis.runtimes.langgraph.agents.research_agent import LlmResearchAgent
from stockwise_analysis.runtimes.langgraph.nodes.nodes import current_run_observations
from stockwise_analysis.tools.capabilities import build_default_capability_registry
from stockwise_analysis.tools.coverage import evaluate_coverage
from stockwise_analysis.tools.requirement_planner import CapabilityRequirementPlanner


def test_default_registry_contains_unified_capabilities_only():
    registry = build_default_capability_registry()

    assert len(registry.list()) == 14
    assert registry.contains("market.get_realtime_quote")
    assert registry.contains("research.web_search")
    assert all("mcp" not in spec.name for spec in registry.list())


def test_technical_plan_keeps_optional_tools_out_until_requested():
    planner = CapabilityRequirementPlanner(build_default_capability_registry())

    basic = planner.plan(
        {"analysis_type": "technical", "symbol": "600519"},
        {"message": "分析 600519 技术趋势"},
    )
    with_flow = planner.plan(
        {"analysis_type": "technical", "symbol": "600519"},
        {"message": "分析 600519 技术趋势和资金流"},
    )

    assert [item.capability for item in basic] == [
        "market.get_realtime_quote",
        "market.get_historical_prices",
    ]
    assert with_flow[-1].capability == "market.get_money_flow"
    assert with_flow[-1].required is False


def test_comprehensive_plan_has_required_core_and_bounded_candidates():
    planner = CapabilityRequirementPlanner(build_default_capability_registry())
    requirements = planner.plan(
        {"analysis_type": "comprehensive", "symbol": "600519"},
        {"message": "全面分析 600519"},
    )
    candidates = planner.candidate_manifest("comprehensive")

    required = {item.capability for item in requirements if item.required}
    optional = {item.capability for item in requirements if not item.required}
    assert required == {
        "market.get_realtime_quote",
        "market.get_historical_prices",
        "market.get_financial_statements",
        "market.get_valuation",
    }
    assert optional == {
        "market.get_industry_context",
        "market.get_money_flow",
        "market.get_news",
        "research.web_search",
    }
    assert len(candidates) == 8


def test_coverage_distinguishes_required_and_optional_gaps():
    requirements = [
        {"capability": "market.get_realtime_quote", "required": True},
        {"capability": "market.get_news", "required": False},
    ]

    missing_required = evaluate_coverage(requirements, [])
    missing_optional = evaluate_coverage(
        requirements,
        [{"capability": "market.get_realtime_quote", "status": "SUCCESS"}],
    )
    partial_available = evaluate_coverage(
        requirements,
        [
            {"capability": "market.get_realtime_quote", "status": "SUCCESS"},
            {"capability": "market.get_news", "status": "PARTIAL"},
        ],
    )

    assert missing_required.status == "LIMITED"
    assert missing_optional.status == "PARTIAL"
    assert partial_available.status == "PARTIAL"
    assert partial_available.missing_optional == []


def test_current_run_observations_do_not_reuse_previous_turn_market_data():
    state = {
        "_observation_start_index": 1,
        "observations": [
            {"observation_id": "old", "capability": "market.get_realtime_quote"},
            {"observation_id": "new", "capability": "market.get_realtime_quote"},
        ],
    }

    assert current_run_observations(state) == [state["observations"][1]]


class _Response:
    def __init__(self, content: str):
        self.content = content


class _HallucinatingLlm:
    def invoke(self, messages):
        return _Response(json.dumps({
            "action": "mcp.raw_unapproved_tool",
            "arguments": {},
            "reason": "hallucinated",
        }))


def test_llm_action_outside_candidate_whitelist_falls_back_to_planned_requirement():
    agent = LlmResearchAgent(_HallucinatingLlm())
    requirements = [{
        "capability": "market.get_realtime_quote",
        "arguments": {"symbol": "600519"},
        "reason": "required",
    }]

    action = agent.choose_next_action([], requirements)

    assert action.action == "market.get_realtime_quote"
    assert action.arguments == {"symbol": "600519"}
