"""Deep Research 金标准 / 图路径烟雾测试。"""

from __future__ import annotations

import pytest
from tests.tools.deep_research_eval.harness import run_gold_suite
from tests.tools.helpers_atomic_search import FakeAtomicSearchPort
from tests.tools.helpers_deep_research_model import RuleBasedDeepResearchModel

from bdlh_runtime.tools.deep_research import (
    DeepResearchRequest,
    run_deep_research,
)
from bdlh_runtime.tools.deep_research.graph import build_deep_research_graph


@pytest.mark.asyncio
async def test_deep_research_graph_phases_reach_assembled():
    graph = build_deep_research_graph(
        atomic_search=FakeAtomicSearchPort(),
        research_model=RuleBasedDeepResearchModel(),
    )
    request = DeepResearchRequest.model_validate(
        {
            "request_id": "g1",
            "question": "比较舆情与风险",
            "objective": "收集来源",
            "research_topics": ["舆情", "风险"],
            "budget": {"runtime_seconds": 30, "search_call_limit": 6},
        }
    )
    from time import perf_counter

    final = await graph.ainvoke(
        {
            "request": request.model_dump(),
            "brief": "",
            "units": [],
            "sources": [],
            "findings": [],
            "limitations": [],
            "unit_summaries": [],
            "deep_trigger_reasons": ["graph_test"],
            "search_calls": 0,
            "model_calls": 0,
            "source_counter": 0,
            "supervisor_round": 0,
            "provider_failed": False,
            "budget_exhausted": False,
            "started_perf": perf_counter(),
            "allow_complete": False,
            "phase": "start",
            "bundle": None,
        }
    )
    assert final["phase"] == "assembled"
    assert final["brief"]
    assert final["bundle"]["status"] == "PARTIAL"
    assert final["bundle"]["sources"]
    assert final["bundle"]["usage"]["research_units"] >= 2


@pytest.mark.asyncio
async def test_run_deep_research_delegates_to_graph():
    bundle = await run_deep_research(
        DeepResearchRequest.model_validate(
            {
                "request_id": "g2",
                "question": "政策变化",
                "objective": "来源",
                "research_topics": ["政策"],
            }
        ),
        atomic_search=FakeAtomicSearchPort(),
        research_model=RuleBasedDeepResearchModel(),
    )
    assert bundle.status in {"PARTIAL", "LIMITED", "FAILED"}
    assert bundle.research_brief


@pytest.mark.asyncio
async def test_gold_suite_meets_dev_positive_usable_floor():
    results, metrics = await run_gold_suite()
    assert all(r.ok for r in results), {r.case_id: r.detail for r in results if not r.ok}
    # 故意失败样本不计；正向用例端到端可用率应对齐 §17.2 ≥75%
    assert metrics["e2e_usable_rate_on_positive"] >= 0.75
    assert metrics["pass_rate"] == 1.0
