from __future__ import annotations

from typing import Any

import pytest

from stockwise_analysis.contracts.analysis import AnalysisInput
from stockwise_analysis.contracts.observation import (
    DataQuality,
    Observation,
    ProvenanceRecord,
)
from stockwise_analysis.contracts.workflow import TaskSpec, WorkflowPlan
from stockwise_analysis.runtimes.langgraph.nodes.nodes import assemble_analysis
from stockwise_analysis.runtimes.shared import assemble_analysis_input
from stockwise_analysis.tools.capabilities import build_default_capability_registry
from stockwise_analysis.tools.requirement_planner import CapabilityRequirementPlanner


REQUESTED_TOPICS = {
    "market_snapshot": set(),
    "technical": {"news", "money_flow"},
    "fundamental": {"news", "industry", "web_research"},
    "valuation": {"news", "industry", "web_research"},
    "comprehensive": set(),
}


def observation_data(capability: str) -> Any:
    data_by_capability: dict[str, Any] = {
        "market.resolve_instrument": {"symbol": "600519", "name": "贵州茅台"},
        "market.get_realtime_quote": {"symbol": "600519", "price": 1500.0},
        "market.get_historical_prices": [
            {"date": "2026-08-08", "close": 1490.0},
            {"date": "2026-08-09", "close": 1500.0},
        ],
        "market.get_financial_statements": {
            "revenue": 1000.0,
            "net_profit": 300.0,
        },
        "market.get_valuation": {"pe": 20.0, "pb": 6.0},
        "market.get_industry_context": {"industry": "白酒"},
        "market.get_money_flow": {"net_inflow": 1_000_000},
        "market.get_news": {"items": [{"title": "公司公告"}]},
        "research.web_search": {
            "results": [{"title": "公开资料", "url": "https://example.com"}]
        },
    }
    return data_by_capability[capability]


def make_observations(capabilities: list[str]) -> list[Observation]:
    return [
        Observation(
            observation_id=f"obs-{index}",
            capability=capability,
            status="SUCCESS",
            data=observation_data(capability),
            data_quality=DataQuality(completeness=1.0, quality_status="OK"),
            provenance=[
                ProvenanceRecord(
                    source="fixture",
                    tool=capability,
                    retrieved_at="2026-08-10T00:00:00Z",
                )
            ],
        )
        for index, capability in enumerate(capabilities)
    ]


@pytest.mark.parametrize("analysis_type", list(REQUESTED_TOPICS))
def test_legacy_node_and_finance_runtime_share_identical_assembly(
    analysis_type: str,
) -> None:
    planner = CapabilityRequirementPlanner(build_default_capability_registry())
    requirements = planner.plan_explicit(
        analysis_type=analysis_type,
        symbol="600519",
        requested_topics=REQUESTED_TOPICS[analysis_type],
    )
    requirement_dicts = [item.model_dump() for item in requirements]
    observations = make_observations(
        ["market.resolve_instrument", *[item.capability for item in requirements]]
    )

    direct = assemble_analysis_input(
        analysis_id=f"run-{analysis_type}",
        analysis_type=analysis_type,
        symbol="600519",
        observations=observations,
        requirements=requirement_dicts,
    )
    plan = WorkflowPlan(
        plan_id=f"plan-{analysis_type}",
        analysis_type=analysis_type,
        tasks=[
            TaskSpec(
                task_id="assemble-analysis",
                task_type="assemble_analysis",
                status="RUNNING",
            )
        ],
        current_task_id="assemble-analysis",
    )
    node_result = assemble_analysis(
        {
            "run_id": f"run-{analysis_type}",
            "intent": {"analysis_type": analysis_type, "symbol": "600519"},
            "observations": [item.model_dump() for item in observations],
            "_observation_start_index": 0,
            "data_requirements": requirement_dicts,
            "workflow_plan": plan.model_dump(),
            "current_task_id": "assemble-analysis",
        }
    )

    assert AnalysisInput.model_validate(node_result["analysis_input"]) == direct
    completed_plan = WorkflowPlan.model_validate(node_result["workflow_plan"])
    assert completed_plan.tasks[0].status == "COMPLETED"
