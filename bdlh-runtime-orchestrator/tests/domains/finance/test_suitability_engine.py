"""SuitabilityEngine v0 规则与聚合回归。"""

from __future__ import annotations

from datetime import UTC, datetime

from bdlh_runtime.domains.contracts import ConfidenceAssessment
from bdlh_runtime.domains.finance.contracts import (
    FinancialDataMode,
    FinancialInstrument,
    FinancialSnapshot,
    LiquiditySnapshot,
    RiskProfile,
    StockResearchResult,
    Technicals,
)
from bdlh_runtime.domains.finance.suitability_engine import SuitabilityEngine


def _research(
    *,
    coverage: str = "COMPLETE",
    confidence: str = "HIGH",
    mdd: float | None = 25,
    vol: float | None = 22,
) -> StockResearchResult:
    indicators: dict[str, float] = {}
    if mdd is not None:
        indicators["max_drawdown_pct"] = mdd
    if vol is not None:
        indicators["annualized_volatility_pct"] = vol
    return StockResearchResult(
        instrument=FinancialInstrument(symbol="600519"),
        coverage=coverage,  # type: ignore[arg-type]
        confidence=ConfidenceAssessment(level=confidence, coverage_status=coverage),  # type: ignore[arg-type]
        technicals=Technicals(indicators=indicators) if indicators else None,
    )


def _snapshot(
    *,
    risk_level: str = "BALANCED",
    max_loss: float = 30,
    data_mode: FinancialDataMode = FinancialDataMode.LIVE,
    liquid: float = 100_000,
    needs: float = 20_000,
    is_mock: bool | None = None,
) -> FinancialSnapshot:
    mock = bool(is_mock) if is_mock is not None else data_mode == FinancialDataMode.MOCK
    return FinancialSnapshot(
        user_id="user-1",
        captured_at=datetime(2026, 8, 11, tzinfo=UTC),
        data_mode=data_mode,
        is_mock=mock,
        provenance=["obs-account", "obs-risk"],
        completeness="COMPLETE",
        risk_profile=RiskProfile(
            risk_level=risk_level,  # type: ignore[arg-type]
            max_loss_tolerance_pct=max_loss,
            source="obs-risk",
        ),
        liquidity=LiquiditySnapshot(
            status="OK",
            liquid_assets=liquid,
            near_term_cash_needs=needs,
        ),
    )


def test_engine_insufficient_when_research_partial() -> None:
    assessment = SuitabilityEngine().evaluate(
        research=_research(coverage="PARTIAL"),
        snapshot=_snapshot(),
    )
    assert assessment.result == "INSUFFICIENT_INFORMATION"
    assert assessment.rule_set_version == "suitability-v0.1"


def test_engine_insufficient_when_snapshot_mock() -> None:
    assessment = SuitabilityEngine().evaluate(
        research=_research(),
        snapshot=_snapshot(data_mode=FinancialDataMode.MOCK),
    )
    assert assessment.result == "INSUFFICIENT_INFORMATION"


def test_engine_blocks_conservative_with_high_band() -> None:
    assessment = SuitabilityEngine().evaluate(
        research=_research(mdd=45, vol=40),
        snapshot=_snapshot(risk_level="CONSERVATIVE", max_loss=50),
    )
    assert assessment.market_risk_proxy is not None
    assert assessment.market_risk_proxy.band == "HIGH"
    assert assessment.result == "CURRENTLY_NOT_SUITABLE"
    assert any(item.rule_id == "SUIT-RISK-LEVEL-001" and item.outcome == "BLOCK" for item in assessment.rule_evaluations)


def test_engine_blocks_when_mdd_exceeds_tolerance() -> None:
    assessment = SuitabilityEngine().evaluate(
        research=_research(mdd=30, vol=15),
        snapshot=_snapshot(risk_level="BALANCED", max_loss=20),
    )
    assert assessment.result == "CURRENTLY_NOT_SUITABLE"
    assert any(item.rule_id == "SUIT-MAX-LOSS-001" and item.outcome == "BLOCK" for item in assessment.rule_evaluations)


def test_engine_conditional_when_mdd_equals_tolerance() -> None:
    assessment = SuitabilityEngine().evaluate(
        research=_research(mdd=20, vol=15),
        snapshot=_snapshot(risk_level="BALANCED", max_loss=20),
    )
    assert assessment.result == "CONDITIONALLY_SUITABLE"
    assert any(
        item.rule_id == "SUIT-MAX-LOSS-001" and item.outcome == "CONDITIONAL" for item in assessment.rule_evaluations
    )


def test_engine_caps_at_conditionally_suitable_without_proposed_amount() -> None:
    assessment = SuitabilityEngine().evaluate(
        research=_research(mdd=10, vol=12),
        snapshot=_snapshot(risk_level="AGGRESSIVE", max_loss=40),
    )
    assert assessment.result == "CONDITIONALLY_SUITABLE"
    assert assessment.proposed_allocation_confirmed is False
    assert any(item.condition_id == "SUITABILITY_PROPOSED_AMOUNT_REQUIRED" for item in assessment.required_conditions)
    assert all(item.outcome in {"PASS", "UNKNOWN"} for item in assessment.rule_evaluations if item.critical)
