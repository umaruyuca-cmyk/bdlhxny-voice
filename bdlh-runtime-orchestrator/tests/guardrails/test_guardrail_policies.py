"""M4 四时点 Guardrail 最低策略回归。"""

from bdlh_runtime.cognitive import CognitiveAction, CognitiveActionType, PublicResponse
from bdlh_runtime.domains.contracts import DomainBudget, DomainOperation, DomainRequest
from bdlh_runtime.guardrails import (
    DefaultActionGuardrail,
    DefaultDataQualityGuardrail,
    DefaultPlanGuardrail,
    DefaultResponseGuardrail,
    GuardrailContext,
    GuardrailDecision,
)


def _context(*actions: str) -> GuardrailContext:
    return GuardrailContext(
        run_id="run-1",
        authenticated_user_id="user-1",
        enabled_actions=frozenset(actions),
        enabled_domains=frozenset({"example"}),
        authorized_operations=frozenset({"READ_PUBLIC_RESEARCH"}),
    )


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
    assert guardrail.evaluate_response(
        PublicResponse(
            response_kind="DOMAIN_RESULT",
            message="研究完成",
            evidence_refs=["e1"],
            sections=[{"section_type": "FINDINGS", "title": "结论", "items": ["建议立即买入"]}],
        ),
        context=_context(),
    ).audit_code == "TRADING_SEMANTICS_BLOCKED"
    assert guardrail.evaluate_response(PublicResponse(response_kind="DOMAIN_RESULT", message="研究完成"), context=_context()).audit_code == "EVIDENCE_REQUIRED"


def test_plan_rejects_excessive_budget_and_non_read_only_objective() -> None:
    guardrail = DefaultPlanGuardrail()
    excessive = DomainRequest(
        request_id="request-1",
        domain="example",
        authenticated_user_id="user-1",
        objective="只读分析",
        authorized_operations={DomainOperation.READ_PUBLIC_RESEARCH},
        budget=DomainBudget(tool_call_limit=21, runtime_seconds=5),
    )
    action = CognitiveAction(
        action_type=CognitiveActionType.INVOKE_DOMAIN,
        reason_code="READ",
        reason="读取",
        domain_request=excessive,
    )
    assert guardrail.evaluate_plan(action, context=_context("INVOKE_DOMAIN")).audit_code == "PLAN_BUDGET_EXCEEDED"

    trading = excessive.model_copy(update={
        "objective": "execute trade after research",
        "budget": DomainBudget(tool_call_limit=1, runtime_seconds=5),
    })
    action = action.model_copy(update={"domain_request": trading})
    assert guardrail.evaluate_plan(action, context=_context("INVOKE_DOMAIN")).audit_code == "PLAN_OUT_OF_READ_ONLY_SCOPE"


def test_action_rejects_cross_user_domain_request() -> None:
    request = DomainRequest(
        request_id="request-1",
        domain="example",
        authenticated_user_id="other-user",
        objective="只读分析",
        authorized_operations={DomainOperation.READ_PUBLIC_RESEARCH},
        budget=DomainBudget(tool_call_limit=1, runtime_seconds=5),
    )
    action = CognitiveAction(
        action_type=CognitiveActionType.INVOKE_DOMAIN,
        reason_code="READ",
        reason="读取",
        domain_request=request,
    )
    result = DefaultActionGuardrail().evaluate_action(action, context=_context("INVOKE_DOMAIN"))
    assert result.audit_code == "DOMAIN_IDENTITY_MISMATCH"


def test_data_quality_rejects_coverage_upgrade_conflict() -> None:
    result = DefaultDataQualityGuardrail().evaluate_data_quality(
        {"status": "COMPLETE", "confidence": {"coverage_status": "LIMITED"}},
        context=_context(),
    )
    assert result.audit_code == "COVERAGE_STATUS_CONFLICT"


def test_response_modifies_domain_result_when_limitations_exist() -> None:
    response = PublicResponse(
        response_kind="DOMAIN_RESULT",
        message="研究完成",
        evidence_refs=["evidence-1"],
        limitations=["新闻覆盖不完整"],
    )
    result = DefaultResponseGuardrail().evaluate_response(response, context=_context())

    assert result.decision == GuardrailDecision.MODIFY
    assert result.audit_code == "LIMITATIONS_PROPAGATED"
    assert result.replacement is not None
    assert result.replacement.response_kind == "LIMITED"
