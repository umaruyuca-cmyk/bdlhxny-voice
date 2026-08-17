"""M3 fail-closed Suitability 前置评估回归。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bdlh_runtime.domains.contracts import ConfidenceAssessment
from bdlh_runtime.domains.finance.contracts import (
    FinancialDataMode,
    FinancialInstrument,
    FinancialSnapshot,
    LiquiditySnapshot,
    ConcentrationThreshold,
    MarketRiskProxy,
    MarketRiskProxyThresholds,
    RiskProfile,
    StockResearchResult,
    SuitabilityAssessment,
    SuitabilityRuleEvaluation,
    SuitabilityV0RuleSet,
)
from bdlh_runtime.domains.finance.suitability_preflight import (
    PENDING_RULE_IDS,
    PENDING_RULE_SET_VERSION,
    SuitabilityPreflight,
    SuitabilityPreflightError,
)


def _research(*, coverage: str = "COMPLETE") -> StockResearchResult:
    return StockResearchResult(
        instrument=FinancialInstrument(symbol="600519"),
        coverage=coverage,
        confidence=ConfidenceAssessment(level="HIGH", coverage_status=coverage),
    )


def _snapshot(**overrides: object) -> FinancialSnapshot:
    values: dict[str, object] = {
        "user_id": "user-1",
        "captured_at": datetime(2026, 8, 11, tzinfo=UTC),
        "data_mode": FinancialDataMode.LIVE,
        "provenance": ["obs-account", "obs-risk-profile"],
        "completeness": "COMPLETE",
        "risk_profile": RiskProfile(
            risk_level="BALANCED",
            max_loss_tolerance_pct=15,
            source="obs-risk-profile",
        ),
        "liquidity": LiquiditySnapshot(
            status="OK",
            liquid_assets=100_000,
            near_term_cash_needs=20_000,
        ),
    }
    values.update(overrides)
    return FinancialSnapshot(**values)


def test_preflight_is_deterministic_and_never_returns_personalized_result() -> None:
    assessment = SuitabilityPreflight().evaluate(
        research=_research(),
        snapshot=_snapshot(),
    )

    assert assessment.result == "INSUFFICIENT_INFORMATION"
    assert assessment.rule_set_version == PENDING_RULE_SET_VERSION
    assert assessment.rule_ids == list(PENDING_RULE_IDS)
    assert assessment.evidence_refs == ["obs-account", "obs-risk-profile"]
    assert assessment.required_conditions[0].condition_id == (
        "SUITABILITY_RULE_SET_APPROVAL_REQUIRED"
    )
    assert "ADR-004 rule thresholds and aggregation are not approved" in assessment.limitations


def test_preflight_preserves_missing_input_limitations_without_relaxing_gate() -> None:
    assessment = SuitabilityPreflight().evaluate(
        research=_research(coverage="LIMITED"),
        snapshot=_snapshot(
            data_mode=FinancialDataMode.MOCK,
            is_mock=True,
            completeness="LIMITED",
            risk_profile=None,
            liquidity=None,
        ),
    )

    assert assessment.result == "INSUFFICIENT_INFORMATION"
    assert set(assessment.limitations) >= {
        "Research coverage is not COMPLETE",
        "Snapshot data_mode cannot support personalization",
        "Financial snapshot is not COMPLETE",
        "Risk profile risk_level is unavailable",
        "Risk profile max_loss_tolerance_pct is unavailable",
        "Liquidity facts are unavailable",
        "ADR-004 rule thresholds and aggregation are not approved",
    }


def test_preflight_rejects_untraceable_snapshot() -> None:
    with pytest.raises(SuitabilityPreflightError, match="SUITABILITY_EVIDENCE_REQUIRED"):
        SuitabilityPreflight().evaluate(
            research=_research(),
            snapshot=_snapshot(provenance=[]),
        )


def test_market_risk_proxy_cannot_infer_low_without_objective_input() -> None:
    with pytest.raises(ValueError, match="objective inputs"):
        MarketRiskProxy(band="LOW")

    assert MarketRiskProxy(band="UNKNOWN").band == "UNKNOWN"


def test_known_rule_evaluation_requires_traceable_evidence() -> None:
    with pytest.raises(ValueError, match="require evidence_refs"):
        SuitabilityRuleEvaluation(
            rule_id="SUIT-LIQUIDITY-001",
            outcome="PASS",
            critical=True,
            reason_code="LIQUIDITY_BUFFER_OK",
            public_reason="可变现资产覆盖近期资金需求。",
        )


def test_suitable_result_requires_confirmed_proposed_allocation() -> None:
    with pytest.raises(ValueError, match="proposed allocation confirmation"):
        SuitabilityAssessment(
            rule_set_version="suitability-v0.1",
            rule_ids=["SUIT-LIQUIDITY-001"],
            evidence_refs=["obs-account"],
            result="SUITABLE",
        )


def test_unapproved_rule_set_cannot_carry_approval_metadata() -> None:
    common = {
        "version": "suitability-v0.1-draft",
        "status": "REVIEW_CHANGES_REQUIRED",
        "rule_ids": list(PENDING_RULE_IDS),
        "critical_rule_ids": set(PENDING_RULE_IDS[:-1]),
        "market_risk_proxy_thresholds": MarketRiskProxyThresholds(
            medium_max_drawdown_pct=20,
            high_max_drawdown_pct=40,
            medium_annualized_volatility_pct=20,
            high_annualized_volatility_pct=35,
            minimum_observation_count=244,
            price_adjustment="FORWARD",
        ),
        "single_position_thresholds": {
            "CONSERVATIVE": ConcentrationThreshold(
                conditional_above_pct=15, block_above_pct=20
            ),
            "BALANCED": ConcentrationThreshold(
                conditional_above_pct=20, block_above_pct=30
            ),
            "AGGRESSIVE": ConcentrationThreshold(
                conditional_above_pct=30, block_above_pct=40
            ),
        },
        "industry_thresholds": {
            "CONSERVATIVE": ConcentrationThreshold(
                conditional_above_pct=30, block_above_pct=40
            ),
            "BALANCED": ConcentrationThreshold(
                conditional_above_pct=40, block_above_pct=50
            ),
            "AGGRESSIVE": ConcentrationThreshold(
                conditional_above_pct=50, block_above_pct=60
            ),
        },
        "liquidity_pass_buffer_ratio": 1.2,
    }

    draft = SuitabilityV0RuleSet(**common)
    assert draft.status == "REVIEW_CHANGES_REQUIRED"
    assert draft.liquidity_equal_to_needs_outcome == "CONDITIONAL"

    with pytest.raises(ValueError, match="cannot carry approval metadata"):
        SuitabilityV0RuleSet(
            **common,
            approval_ref="ADR-004#approval",
            approved_at=datetime(2026, 8, 12, tzinfo=UTC),
        )
