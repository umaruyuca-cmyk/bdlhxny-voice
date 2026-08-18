from __future__ import annotations

from typing import Any

import pytest

from bdlh_runtime.contracts.analysis import AnalysisInput
from bdlh_runtime.contracts.observation import (
    DataQuality,
    Observation,
    ProvenanceRecord,
)
from bdlh_runtime.contracts.workflow import TaskSpec, WorkflowPlan
from bdlh_runtime.runtimes.langgraph.nodes.nodes import assemble_analysis
from bdlh_runtime.runtimes.shared import assemble_analysis_input
from tests.helpers_registry import seeded_snapshot


def _topic_map() -> dict[str, list[str]]:
    snapshot = seeded_snapshot()
    return {
        topic: snapshot.topic_capabilities_for(topic)
        for topic in ("news", "money_flow", "industry", "web_research")
    }


#: 重写：场景 = 基线面板（resolve+quote）+ 附加 topics
REQUESTED_TOPICS = {
    "baseline": set(),
    "news_flow": {"news", "money_flow"},
    "research_ext": {"industry", "web_research"},
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


@pytest.mark.parametrize("scenario", list(REQUESTED_TOPICS))
def test_legacy_node_and_finance_runtime_share_identical_assembly(
    scenario: str,
) -> None:
    topics = REQUESTED_TOPICS[scenario]
    topic_map = _topic_map()
    names = ["market.resolve_instrument", "market.get_realtime_quote"]
    for topic in sorted(topics):
        for capability in topic_map.get(topic, []):
            if capability not in names:
                names.append(capability)
    observations = make_observations(names)

    direct = assemble_analysis_input(
        analysis_id=f"run-{scenario}",
        symbol="600519",
        observations=observations,
        requested_capabilities=names,
    )
    plan = WorkflowPlan(
        plan_id=f"plan-{scenario}",
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
            "run_id": f"run-{scenario}",
            "understand": {"entities": {"instruments": ["600519"]}},
            "observations": [item.model_dump() for item in observations],
            "_observation_start_index": 0,
            "allowed": names,
            "workflow_plan": plan.model_dump(),
            "current_task_id": "assemble-analysis",
        }
    )

    assert AnalysisInput.model_validate(node_result["analysis_input"]) == direct
    completed_plan = WorkflowPlan.model_validate(node_result["workflow_plan"])
    assert completed_plan.tasks[0].status == "COMPLETED"
