"""M4 四时点 Guardrail 最低策略回归。"""

from bdlh_runtime.cognitive import CognitiveAction, CognitiveActionType, PublicResponse
from bdlh_runtime.guardrails import (
    DefaultActionGuardrail,
    DefaultDataQualityGuardrail,
    DefaultPlanGuardrail,
    DefaultResponseGuardrail,
    GuardrailContext,
)


def _context(*actions: str) -> GuardrailContext:
    return GuardrailContext(run_id="run-1", authenticated_user_id="user-1", enabled_actions=frozenset(actions))


def _respond() -> CognitiveAction:
    return CognitiveAction(action_type=CognitiveActionType.RESPOND, reason_code="STABLE_KNOWLEDGE", reason="稳定知识")


def test_plan_and_action_reject_unenabled_actions() -> None:
    action = _respond()
    assert DefaultPlanGuardrail().evaluate_plan(action, context=_context()).audit_code == "ACTION_NOT_ENABLED"
    assert DefaultActionGuardrail().evaluate_action(action, context=_context()).audit_code == "ACTION_NOT_ENABLED"


def test_data_quality_rejects_fixture_and_unavailable_data() -> None:
    guardrail = DefaultDataQualityGuardrail()
    assert guardrail.evaluate_data_quality({"status": "SUCCESS", "data_mode": "MOCK"}, context=_context()).audit_code == "NON_PRODUCTION_DATA"
    assert guardrail.evaluate_data_quality({"status": "UNAVAILABLE"}, context=_context()).audit_code == "DATA_UNAVAILABLE"


def test_response_blocks_trading_semantics_and_requires_evidence() -> None:
    guardrail = DefaultResponseGuardrail()
    assert guardrail.evaluate_response(PublicResponse(response_kind="ANSWER", message="建议立即买入"), context=_context()).audit_code == "TRADING_SEMANTICS_BLOCKED"
    assert guardrail.evaluate_response(PublicResponse(response_kind="DOMAIN_RESULT", message="研究完成"), context=_context()).audit_code == "EVIDENCE_REQUIRED"
