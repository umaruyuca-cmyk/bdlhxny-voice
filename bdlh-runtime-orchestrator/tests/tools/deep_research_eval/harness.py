"""Deep Research 离线评测 harness（ADR-016 §17.2 开发门槛骨架）。

默认用 FakeAtomicSearch + RuleBased 模型，不打真实百炼/DeepSeek。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bdlh_runtime.guardrails import evaluate_research_observation
from bdlh_runtime.tools.deep_research import (
    DEEP_SEARCH_CAPABILITY,
    DeepResearchRequest,
    FakeAtomicSearchPort,
    RuleBasedDeepResearchModel,
    run_deep_research,
)
from bdlh_runtime.tools.deep_research.atomic_search import AtomicSearchBatch, AtomicSearchHit
from bdlh_runtime.tools.deep_research.bailian_provider import sanitize_snippet

GOLD_PATH = Path(__file__).with_name("gold_cases.json")


@dataclass
class CaseResult:
    case_id: str
    ok: bool
    usable: bool
    status: str
    source_count: int
    detail: str = ""


class _EmptyAtomicSearch(FakeAtomicSearchPort):
    async def search(self, request):  # type: ignore[override]
        return AtomicSearchBatch(request_id=request.request_id, status="EMPTY", hits=[])


class _UnavailableAtomicSearch(FakeAtomicSearchPort):
    async def search(self, request):  # type: ignore[override]
        return AtomicSearchBatch(
            request_id=request.request_id,
            status="UNAVAILABLE",
            error_code="ATOMIC_SEARCH_UNAVAILABLE",
            error_message="eval unavailable provider",
        )


def load_gold_cases(path: Path | None = None) -> list[dict[str, Any]]:
    data = json.loads((path or GOLD_PATH).read_text(encoding="utf-8"))
    return list(data.get("cases") or [])


def _build_port(case: dict[str, Any]) -> FakeAtomicSearchPort:
    if case.get("atomic_unavailable"):
        return _UnavailableAtomicSearch()
    if case.get("empty_hits"):
        return _EmptyAtomicSearch()
    canned = case.get("canned_hits")
    if canned:
        hits = [
            AtomicSearchHit(
                title=str(row.get("title") or "t"),
                url=str(row.get("url") or "https://example.test/x"),
                summary=sanitize_snippet(str(row.get("summary") or "")),
                domain="example.test",
                retrieved_at="2026-08-15T00:00:00Z",
                provider="fake-bailian",
            )
            for row in canned
        ]
        return FakeAtomicSearchPort(canned_hits=hits)
    return FakeAtomicSearchPort()


async def run_case(case: dict[str, Any]) -> CaseResult:
    request = DeepResearchRequest.model_validate(case["request"])
    bundle = await run_deep_research(
        request,
        atomic_search=_build_port(case),
        research_model=RuleBasedDeepResearchModel(),
        deep_trigger_reasons=["eval_harness"],
    )
    usable = bundle.status in {"PARTIAL", "COMPLETE"} and len(bundle.sources) >= 1
    # Result 时点：对齐 Data Guardrail（离线）
    guard_hit = evaluate_research_observation(
        {
            "capability": DEEP_SEARCH_CAPABILITY,
            "status": "SUCCESS" if usable else "FAILED",
            "data": bundle.model_dump(),
        }
    )
    if guard_hit is not None:
        usable = False

    ok = True
    detail_parts: list[str] = []

    if case.get("expect_usable") and not usable:
        ok = False
        detail_parts.append("expected_usable")
    if case.get("expect_usable") is False and usable:
        ok = False
        detail_parts.append("unexpected_usable")

    min_sources = int(case.get("min_sources") or 0)
    if usable and len(bundle.sources) < min_sources:
        ok = False
        detail_parts.append(f"min_sources<{min_sources}")
    if (not usable) and min_sources and case.get("expect_usable"):
        pass  # already failed expected_usable

    if case.get("forbid_complete_without_sources") and bundle.status == "COMPLETE" and not bundle.sources:
        ok = False
        detail_parts.append("complete_without_sources")

    forbid_status = set(case.get("forbid_status") or [])
    if bundle.status in forbid_status:
        ok = False
        detail_parts.append(f"forbid_status:{bundle.status}")

    allowed = case.get("allowed_statuses")
    if allowed and bundle.status not in set(allowed):
        ok = False
        detail_parts.append(f"status_not_allowed:{bundle.status}")

    must_any = case.get("must_limitation_any") or []
    if must_any and not any(item in bundle.limitations for item in must_any):
        ok = False
        detail_parts.append("missing_limitation")

    max_search = case.get("max_search_calls")
    if max_search is not None and bundle.usage.search_calls > int(max_search):
        ok = False
        detail_parts.append("search_calls_over_budget")

    banned = [s.lower() for s in (case.get("summary_must_not_contain") or [])]
    blob = " ".join(
        [bundle.research_summary]
        + [s.summary for s in bundle.sources]
        + [f.statement for f in bundle.findings]
    ).lower()
    for token in banned:
        if token in blob:
            ok = False
            detail_parts.append(f"leak:{token}")

    if guard_hit is not None:
        detail_parts.append(f"guardrail:{guard_hit[0]}")

    return CaseResult(
        case_id=str(case["id"]),
        ok=ok,
        usable=usable,
        status=bundle.status,
        source_count=len(bundle.sources),
        detail=";".join(detail_parts),
    )


async def run_gold_suite(path: Path | None = None) -> tuple[list[CaseResult], dict[str, float]]:
    cases = load_gold_cases(path)
    results = [await run_case(case) for case in cases]
    total = len(results) or 1
    usable_rate = sum(1 for r in results if r.usable) / total
    pass_rate = sum(1 for r in results if r.ok) / total
    metrics = {
        "case_count": float(len(results)),
        "pass_rate": pass_rate,
        "e2e_usable_rate": usable_rate,
    }
    expect_usable = [r for r, c in zip(results, cases) if c.get("expect_usable")]
    if expect_usable:
        metrics["e2e_usable_rate_on_positive"] = sum(1 for r in expect_usable if r.usable) / len(
            expect_usable
        )
    return results, metrics
