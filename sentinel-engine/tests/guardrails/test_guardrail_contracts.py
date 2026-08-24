"""M4 Guardrail 契约与独立接口回归。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bdlh_runtime.guardrails import (
    ActionGuardrail,
    DataQualityGuardrail,
    GuardrailContext,
    GuardrailDecision,
    GuardrailResult,
    GuardrailStage,
    PlanGuardrail,
    ResponseGuardrail,
)


def _context() -> GuardrailContext:
    return GuardrailContext(
        run_id="run-1",
        authenticated_user_id="user-1",
        authorized_capabilities=frozenset({"market.get_realtime_quote"}),
        enabled_actions=frozenset({"INVOKE_DOMAIN"}),
    )


def test_allow_result_needs_no_replacement_or_audit_code() -> None:
    result = GuardrailResult[str](
        stage=GuardrailStage.PLAN,
        decision=GuardrailDecision.ALLOW,
    )

    assert result.replacement is None
    assert result.audit_code is None


def test_modify_result_requires_replacement_and_stable_audit_data() -> None:
    result = GuardrailResult[str](
        stage=GuardrailStage.ACTION,
        decision=GuardrailDecision.MODIFY,
        replacement="bounded-action",
        reasons=["动作已收敛到本轮候选集"],
        audit_code="ACTION_MODIFIED_TO_CANDIDATE",
        rule_ids=["ACTION-ALLOWLIST-001"],
    )

    assert result.replacement == "bounded-action"
    with pytest.raises(ValidationError, match="require a replacement"):
        GuardrailResult[str](
            stage=GuardrailStage.ACTION,
            decision=GuardrailDecision.MODIFY,
            reasons=["需要修改"],
            audit_code="ACTION_MODIFIED",
        )


@pytest.mark.parametrize("decision", ["block", "modify", "ask_user"])
def test_non_allow_result_requires_public_reason_and_audit_code(decision: str) -> None:
    values = {
        "stage": GuardrailStage.RESPONSE,
        "decision": decision,
    }
    if decision == "modify":
        values["replacement"] = "safe response"

    with pytest.raises(ValidationError, match="stable audit_code"):
        GuardrailResult[str](**values)


def test_non_modify_result_cannot_carry_replacement() -> None:
    with pytest.raises(ValidationError, match="only modify"):
        GuardrailResult[str](
            stage=GuardrailStage.DATA_QUALITY,
            decision=GuardrailDecision.BLOCK,
            replacement="unexpected",
            reasons=["数据无效"],
            audit_code="DATA_INVALID",
        )


def test_guardrail_context_is_strict_and_immutable() -> None:
    context = _context()

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GuardrailContext(
            **context.model_dump(),
            access_token="must-not-enter-policy-context",
        )
    with pytest.raises(ValidationError, match="frozen"):
        context.read_only = False


class _PlanPolicy:
    def evaluate_plan(self, plan: str, *, context: GuardrailContext) -> GuardrailResult[str]:
        return GuardrailResult(
            stage=GuardrailStage.PLAN,
            decision=GuardrailDecision.ALLOW,
        )


class _ActionPolicy:
    def evaluate_action(self, action: str, *, context: GuardrailContext) -> GuardrailResult[str]:
        return GuardrailResult(
            stage=GuardrailStage.ACTION,
            decision=GuardrailDecision.ALLOW,
        )


class _DataQualityPolicy:
    def evaluate_data_quality(
        self,
        observation: str,
        *,
        context: GuardrailContext,
    ) -> GuardrailResult[str]:
        return GuardrailResult(
            stage=GuardrailStage.DATA_QUALITY,
            decision=GuardrailDecision.ALLOW,
        )


class _ResponsePolicy:
    def evaluate_response(self, response: str, *, context: GuardrailContext) -> GuardrailResult[str]:
        return GuardrailResult(
            stage=GuardrailStage.RESPONSE,
            decision=GuardrailDecision.ALLOW,
        )


def test_four_guardrail_protocols_are_independent_interfaces() -> None:
    assert isinstance(_PlanPolicy(), PlanGuardrail)
    assert isinstance(_ActionPolicy(), ActionGuardrail)
    assert isinstance(_DataQualityPolicy(), DataQualityGuardrail)
    assert isinstance(_ResponsePolicy(), ResponseGuardrail)
    assert not isinstance(_PlanPolicy(), ActionGuardrail)
