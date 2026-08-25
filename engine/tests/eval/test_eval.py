"""eval 题库规模与双模式对照门禁（WO-T2-5）。"""

from __future__ import annotations

import pytest

from bdlh_runtime.tools.catalog import catalog_from_snapshot
from tests.eval.routing_cases import (
    BASELINE_TASK_SUCCESS,
    CATEGORIES,
    MIN_CASES_PER_CATEGORY,
    MIN_TOTAL_CASES,
    ROUTING_CASES,
    cases_by_category,
)
from tests.eval.run_eval import below_baseline, report_to_dict, run_dual_mode_eval


def test_bank_meets_section_11_2_coverage(finance_pack):
    assert len(ROUTING_CASES) >= MIN_TOTAL_CASES
    grouped = cases_by_category()
    assert set(grouped) >= set(CATEGORIES)
    for name in CATEGORIES:
        assert len(grouped[name]) >= MIN_CASES_PER_CATEGORY, name
    ids = [case.id for case in ROUTING_CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.asyncio
async def test_dual_mode_not_below_baseline(registry_snapshot, finance_pack):
    report = await run_dual_mode_eval(catalog_from_snapshot(registry_snapshot))
    payload = report_to_dict(report)
    assert payload["scoped"]["task_success_rate"] >= BASELINE_TASK_SUCCESS
    # search 模式对垂直工具描述依赖场景包 overlay,允许极少量未命中
    assert payload["search"]["task_success_rate"] >= 0.96
    assert payload["search"]["retrieval_hit_rate"] is not None
    assert payload["search"]["retrieval_hit_rate"] >= 0.96
    assert not any(item.startswith("scoped") for item in below_baseline(report))
    assert payload["scoped"]["mean_rounds"] > 0
    assert payload["search"]["mean_rounds"] >= payload["scoped"]["mean_rounds"]
