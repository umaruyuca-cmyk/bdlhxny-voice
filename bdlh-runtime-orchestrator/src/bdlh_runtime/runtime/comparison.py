"""M5 离线同输入质量对照，不执行真实影子流量。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class PathQualitySnapshot:
    """新旧路径公开结果的最小、领域无关质量投影。"""

    status: Literal["COMPLETE", "PARTIAL", "LIMITED", "FAILED"]
    coverage_rank: int
    evidence_refs: frozenset[str] = frozenset()
    limitations: tuple[str, ...] = ()
    provenance_present: bool = False
    authenticity: Literal["LIVE", "USER_CONFIRMED", "UNAVAILABLE", "MOCK", "TEST_FIXTURE"] = "UNAVAILABLE"
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.coverage_rank <= 2:
            raise ValueError("coverage_rank must be 0 (LIMITED), 1 (PARTIAL), or 2 (COMPLETE)")


@dataclass(frozen=True)
class ComparisonResult:
    passed: bool
    regression_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComparisonCase:
    case_id: str
    scenario: Literal[
        "NORMAL", "PARTIAL", "LIMITED", "PROVIDER_FAILURE", "BUDGET_EXHAUSTED"
    ]
    legacy: PathQualitySnapshot
    cognitive: PathQualitySnapshot


class SameInputComparator:
    """阻断新路径真实性、覆盖率、证据和限制披露回归。"""

    _LIMITED_STATUSES = {"PARTIAL", "LIMITED", "FAILED"}

    def compare(self, case: ComparisonCase) -> ComparisonResult:
        regressions: list[str] = []
        new = case.cognitive
        old = case.legacy
        if new.authenticity in {"MOCK", "TEST_FIXTURE"}:
            regressions.append("NON_PRODUCTION_DATA_EXPOSED")
        if new.coverage_rank < old.coverage_rank:
            regressions.append("COVERAGE_REGRESSION")
        if old.provenance_present and not new.provenance_present:
            regressions.append("PROVENANCE_REGRESSION")
        if old.evidence_refs and not new.evidence_refs:
            regressions.append("EVIDENCE_REGRESSION")
        if new.status in self._LIMITED_STATUSES and not new.limitations:
            regressions.append("LIMITATION_DISCLOSURE_MISSING")
        if case.scenario in {"PROVIDER_FAILURE", "BUDGET_EXHAUSTED"}:
            if new.status == "COMPLETE":
                regressions.append("FAILURE_WRAPPED_AS_COMPLETE")
            if not new.error_code:
                regressions.append("STRUCTURED_ERROR_MISSING")
        return ComparisonResult(
            passed=not regressions,
            regression_codes=tuple(dict.fromkeys(regressions)),
        )

    def compare_suite(self, cases: list[ComparisonCase]) -> dict[str, ComparisonResult]:
        case_ids = [case.case_id for case in cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("comparison case_id values must be unique")
        return {case.case_id: self.compare(case) for case in cases}
