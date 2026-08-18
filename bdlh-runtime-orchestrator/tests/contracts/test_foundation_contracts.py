"""SW31 阶段 1 契约回归：``SW31-P1-DOMAIN-CONTRACTS``。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bdlh_runtime.cognitive.contracts import (
    ACTION_NOT_ENABLED,
    ENABLED_ACTION_TYPES,
    CognitiveAction,
    CognitiveActionType,
    is_action_enabled,
)
from bdlh_runtime.domains.contracts import (
    ConfidenceAssessment,
    DomainBudget,
    DomainError,
    DomainOperation,
    DomainOutcome,
    DomainRequest,
)
from bdlh_runtime.domains.finance.contracts import (
    FinancialDataMode,
    FinancialDomainRequest,
    FinancialInstrument,
    FinancialIntent,
    FinancialSnapshot,
    PortfolioImpact,
    PortfolioPosition,
    RiskProfile,
    SuitabilityAssessment,
)
from bdlh_runtime.domains.registry import DomainRegistry


def _budget() -> DomainBudget:
    return DomainBudget(tool_call_limit=4, runtime_seconds=30, model_call_limit=1)


def _domain_request(**overrides) -> DomainRequest:
    values = {
        "request_id": "domain-1",
        "domain": "finance",
        "authenticated_user_id": "user-1",
        "objective": "研究指定股票",
        "success_criteria": ["返回可追溯证据"],
        "authorized_operations": {
            DomainOperation.READ_MARKET_DATA,
            DomainOperation.RUN_ANALYSIS,
        },
        "budget": _budget(),
    }
    values.update(overrides)
    return DomainRequest(**values)


def test_domain_request_round_trip_is_lossless_and_strict() -> None:
    request = _domain_request()

    restored = DomainRequest.model_validate_json(request.model_dump_json())

    assert restored == request
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _domain_request(unbounded_payload={"hidden": "value"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authenticated_user_id", ""),
        ("objective", ""),
        ("authorized_operations", set()),
    ],
)
def test_domain_request_rejects_invalid_boundary_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _domain_request(**{field: value})


def test_domain_budget_rejects_negative_or_zero_runtime() -> None:
    with pytest.raises(ValidationError):
        DomainBudget(tool_call_limit=-1, runtime_seconds=30)
    with pytest.raises(ValidationError):
        DomainBudget(tool_call_limit=1, runtime_seconds=0)


def test_domain_outcome_rejects_final_chat_response_fields() -> None:
    confidence = ConfidenceAssessment(
        level="LOW",
        reasons=["数据不足"],
        coverage_status="LIMITED",
    )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DomainOutcome(
            request_id="domain-1",
            domain="finance",
            status="LIMITED",
            confidence=confidence,
            final_response="不应由领域层生成",
        )

    failed = DomainOutcome(
        request_id="domain-1",
        domain="finance",
        status="FAILED",
        confidence=confidence,
        errors=[DomainError(code="ACTION_NOT_ENABLED", message="not enabled")],
    )
    assert failed.errors[0].code == "ACTION_NOT_ENABLED"
    with pytest.raises(ValidationError, match="requires at least one DomainError"):
        DomainOutcome(
            request_id="domain-1",
            domain="finance",
            status="FAILED",
            confidence=confidence,
        )


def test_financial_request_extends_domain_request_and_validates_intent() -> None:
    with pytest.raises(ValidationError, match="requires exactly one instrument"):
        FinancialDomainRequest(
            **_domain_request().model_dump(),
            financial_intent=FinancialIntent.STOCK_RESEARCH,
        )

    with pytest.raises(ValidationError, match="requires exactly one instrument"):
        FinancialDomainRequest(
            **_domain_request().model_dump(),
            financial_intent=FinancialIntent.STOCK_RESEARCH,
            instruments=[
                FinancialInstrument(symbol="600519"),
                FinancialInstrument(symbol="000001"),
            ],
        )

    research = FinancialDomainRequest(
        **_domain_request().model_dump(),
        instruments=[FinancialInstrument(symbol="600519")],
        requested_topics={"news", "money_flow"},
    )
    assert research.analysis_type == "technical"
    assert research.requested_topics == {"news", "money_flow"}

    planning = FinancialDomainRequest(
        **_domain_request(objective="评估财务目标").model_dump(),
        financial_intent=FinancialIntent.GOAL_PLANNING,
    )

    assert isinstance(planning, DomainRequest)
    assert planning.instruments == []


def test_financial_snapshot_distinguishes_live_mock_and_user_confirmed_data() -> None:
    captured_at = datetime.now(UTC)
    mock = FinancialSnapshot(
        user_id="user-1",
        captured_at=captured_at,
        data_mode=FinancialDataMode.MOCK,
        is_mock=True,
        provenance=["mock-java"],
    )

    assert mock.data_mode == FinancialDataMode.MOCK
    with pytest.raises(ValidationError, match="must set is_mock=true"):
        FinancialSnapshot(
            user_id="user-1",
            captured_at=captured_at,
            data_mode=FinancialDataMode.MOCK,
        )
    with pytest.raises(ValidationError, match="confirmation provenance"):
        FinancialSnapshot(
            user_id="user-1",
            captured_at=captured_at,
            data_mode=FinancialDataMode.USER_CONFIRMED,
        )


def test_suitability_request_requires_one_instrument_and_comprehensive_research() -> None:
    values = _domain_request(objective="评估单一标的适配性").model_dump()

    with pytest.raises(ValidationError, match="requires exactly one instrument"):
        FinancialDomainRequest(
            **values,
            financial_intent=FinancialIntent.SUITABILITY,
        )
    with pytest.raises(ValidationError, match="SUITABILITY_RESEARCH_PROFILE_REQUIRED"):
        FinancialDomainRequest(
            **values,
            financial_intent=FinancialIntent.SUITABILITY,
            instruments=[FinancialInstrument(symbol="600519")],
        )

    request = FinancialDomainRequest(
        **values,
        financial_intent=FinancialIntent.SUITABILITY,
        instruments=[FinancialInstrument(symbol="600519")],
    )
    assert request.analysis_type == "comprehensive"


def test_suitability_assessment_requires_versioned_unique_rule_evidence() -> None:
    assessment = SuitabilityAssessment(
        rule_set_version="suitability-v0.fixture",
        rule_ids=["SUIT-DATA-AUTHENTICITY-001"],
        evidence_refs=["obs-risk-profile"],
        result="INSUFFICIENT_INFORMATION",
    )
    assert assessment.rule_set_version == "suitability-v0.fixture"

    with pytest.raises(ValidationError, match="stable unique references"):
        SuitabilityAssessment(
            rule_set_version="suitability-v0.fixture",
            rule_ids=["rule-1", "rule-1"],
            evidence_refs=["obs-1"],
            result="INSUFFICIENT_INFORMATION",
        )


def test_m3_percentage_contracts_use_percentage_points_in_zero_to_one_hundred() -> None:
    with pytest.raises(ValidationError):
        PortfolioPosition(symbol="600519", weight_pct=101, source="obs-position")
    with pytest.raises(ValidationError):
        RiskProfile(max_loss_tolerance_pct=-1, source="obs-risk")
    with pytest.raises(ValidationError, match="percentage points"):
        PortfolioImpact(current_exposure={"600519": 120})


def test_cognitive_action_is_the_single_nine_action_contract() -> None:
    assert len(CognitiveActionType) == 9
    assert ENABLED_ACTION_TYPES == {
        CognitiveActionType.RESPOND,
        CognitiveActionType.ASK_USER,
        CognitiveActionType.INVOKE_DOMAIN,
    }
    assert ACTION_NOT_ENABLED == "ACTION_NOT_ENABLED"
    assert not is_action_enabled(CognitiveActionType.CREATE_TASK)


def test_cognitive_action_enforces_domain_payload_boundary() -> None:
    with pytest.raises(ValidationError, match="requires a domain_request"):
        CognitiveAction(
            action_type=CognitiveActionType.INVOKE_DOMAIN,
            reason_code="DOMAIN_REQUIRED",
            reason="需要金融领域数据",
        )

    with pytest.raises(ValidationError, match="only INVOKE_DOMAIN"):
        CognitiveAction(
            action_type=CognitiveActionType.RESPOND,
            reason_code="DIRECT_RESPONSE",
            reason="稳定知识问题",
            domain_request=_domain_request(),
        )


def test_domain_registry_does_not_silently_replace_runtime() -> None:
    registry = DomainRegistry()
    runtime = object()

    registry.register("finance", runtime)

    assert registry.get("finance") is runtime
    assert registry.list_domains() == ["finance"]
    with pytest.raises(ValueError, match="already registered"):
        registry.register("finance", object())
