from bdlh_runtime.runtime.comparison import (
    ComparisonCase,
    PathQualitySnapshot,
    SameInputComparator,
)


def _snapshot(
    status: str,
    rank: int,
    *,
    evidence: bool = True,
    limitations: tuple[str, ...] = (),
    error_code: str | None = None,
) -> PathQualitySnapshot:
    return PathQualitySnapshot(
        status=status,  # type: ignore[arg-type]
        coverage_rank=rank,
        evidence_refs=frozenset({"evidence-1"}) if evidence else frozenset(),
        limitations=limitations,
        provenance_present=evidence,
        authenticity="LIVE",
        error_code=error_code,
    )


def test_required_m5_comparison_scenarios_pass_without_quality_regression() -> None:
    cases = [
        ComparisonCase("normal", "NORMAL", _snapshot("COMPLETE", 2), _snapshot("COMPLETE", 2)),
        ComparisonCase("partial", "PARTIAL", _snapshot("PARTIAL", 1, limitations=("old",)), _snapshot("PARTIAL", 1, limitations=("new",))),
        ComparisonCase("limited", "LIMITED", _snapshot("LIMITED", 0, limitations=("old",)), _snapshot("LIMITED", 0, limitations=("new",))),
        ComparisonCase("provider", "PROVIDER_FAILURE", _snapshot("FAILED", 0, limitations=("old",), error_code="PROVIDER"), _snapshot("FAILED", 0, limitations=("new",), error_code="PROVIDER")),
        ComparisonCase("budget", "BUDGET_EXHAUSTED", _snapshot("LIMITED", 0, limitations=("old",), error_code="BUDGET"), _snapshot("LIMITED", 0, limitations=("new",), error_code="BUDGET")),
    ]

    results = SameInputComparator().compare_suite(cases)

    assert set(results) == {"normal", "partial", "limited", "provider", "budget"}
    assert all(result.passed for result in results.values())


def test_comparator_blocks_mock_coverage_and_failure_disclosure_regressions() -> None:
    legacy = _snapshot("COMPLETE", 2)
    cognitive = PathQualitySnapshot(
        status="COMPLETE",
        coverage_rank=0,
        authenticity="MOCK",
    )

    result = SameInputComparator().compare(ComparisonCase(
        "unsafe-provider",
        "PROVIDER_FAILURE",
        legacy,
        cognitive,
    ))

    assert not result.passed
    assert set(result.regression_codes) == {
        "NON_PRODUCTION_DATA_EXPOSED",
        "COVERAGE_REGRESSION",
        "PROVENANCE_REGRESSION",
        "EVIDENCE_REGRESSION",
        "FAILURE_WRAPPED_AS_COMPLETE",
        "STRUCTURED_ERROR_MISSING",
    }
