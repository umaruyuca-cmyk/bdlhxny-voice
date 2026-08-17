from __future__ import annotations

import pytest

from bdlh_runtime.cognitive.contracts import (
    CognitiveAction,
    CognitiveActionType,
    CommunicationPlan,
    InputEvent,
)
from bdlh_runtime.cognitive.orchestrator import CognitiveOrchestrator
from bdlh_runtime.domains.contracts import (
    ConfidenceAssessment,
    DomainBudget,
    DomainFact,
    DomainOperation,
    DomainOutcome,
    DomainRequest,
)
from bdlh_runtime.guardrails import (
    GuardrailContext,
    GuardrailDecision,
    GuardrailResult,
    GuardrailStage,
)


def _event() -> InputEvent:
    return InputEvent(
        event_id="event-1", user_id="user-1", session_id="session-1", message="test"
    )


def _request(request_id: str = "request-1", *, tool_calls: int = 1) -> DomainRequest:
    return DomainRequest(
        request_id=request_id,
        domain="example",
        authenticated_user_id="user-1",
        objective="read validated result",
        authorized_operations={DomainOperation.READ_PUBLIC_RESEARCH},
        budget=DomainBudget(tool_call_limit=tool_calls, runtime_seconds=5),
    )


def _action(request: DomainRequest | None = None) -> CognitiveAction:
    return CognitiveAction(
        action_type=(CognitiveActionType.INVOKE_DOMAIN if request else CognitiveActionType.RESPOND),
        reason_code="TEST",
        reason="safe response",
        domain_request=request,
    )


class Selector:
    def __init__(self, action: CognitiveAction) -> None:
        self.action = action

    async def select(self, event: InputEvent) -> CognitiveAction:
        return self.action


class Dispatcher:
    async def dispatch(self, request: DomainRequest) -> DomainOutcome:
        return DomainOutcome(
            request_id=request.request_id,
            domain=request.domain,
            status="COMPLETE",
            established_facts=[DomainFact(
                fact_id="fact-1",
                statement="validated",
                source_refs=["source-1"],
                directness="DIRECT",
            )],
            confidence=ConfidenceAssessment(
                level="HIGH", reasons=["validated"], coverage_status="COMPLETE"
            ),
        )


class ForgedContinuation:
    async def continue_after(self, *, event: InputEvent, outcome: DomainOutcome) -> CommunicationPlan:
        return CommunicationPlan(
            response_kind="DOMAIN_RESULT",
            response_structure="RESEARCH",
            summary="forged",
            evidence_refs=["not-in-outcome"],
        )


class LoopContinuation:
    async def continue_after(self, *, event: InputEvent, outcome: DomainOutcome) -> CognitiveAction:
        return _action(_request(f"{outcome.request_id}:next", tool_calls=11))


class AskPlanGuardrail:
    def evaluate_plan(self, plan: CognitiveAction, *, context: GuardrailContext) -> GuardrailResult[CognitiveAction]:
        return GuardrailResult(
            stage=GuardrailStage.PLAN,
            decision=GuardrailDecision.ASK_USER,
            audit_code="PLAN_NEEDS_USER",
            rule_ids=["PLAN-TEST-001"],
            reasons=["请确认目标"],
        )


class ModifyPlanGuardrail:
    def evaluate_plan(self, plan: CognitiveAction, *, context: GuardrailContext) -> GuardrailResult[CognitiveAction]:
        replacement = CognitiveAction(
            action_type=CognitiveActionType.RESPOND,
            reason_code="PLAN_MODIFIED",
            reason="已收敛为只读知识回答",
        )
        return GuardrailResult(
            stage=GuardrailStage.PLAN,
            decision=GuardrailDecision.MODIFY,
            replacement=replacement,
            audit_code="PLAN_MODIFIED",
            rule_ids=["PLAN-TEST-002"],
            reasons=["计划已收敛"],
        )


@pytest.mark.asyncio
async def test_forged_evidence_is_blocked_before_public_response() -> None:
    app = CognitiveOrchestrator(
        selector=Selector(_action(_request())),
        dispatcher=Dispatcher(),
        continuation=ForgedContinuation(),
    )

    result = await app.run(_event())

    assert result.response.response_kind == "BLOCKED"
    assert result.response.audit_codes == ["RESPONSE_EVIDENCE_NOT_TRACEABLE"]


@pytest.mark.asyncio
async def test_cumulative_domain_budget_is_enforced_across_steps() -> None:
    app = CognitiveOrchestrator(
        selector=Selector(_action(_request(tool_calls=10))),
        dispatcher=Dispatcher(),
        continuation=LoopContinuation(),
    )

    result = await app.run(_event())

    assert result.response.audit_codes == ["RUN_BUDGET_EXCEEDED"]
    assert result.state.domain_calls_used == 1


@pytest.mark.asyncio
async def test_plan_ask_user_decision_is_executed() -> None:
    app = CognitiveOrchestrator(
        selector=Selector(_action()),
        dispatcher=Dispatcher(),
        plan_guardrail=AskPlanGuardrail(),  # type: ignore[arg-type]
    )

    result = await app.run(_event())

    assert result.response.response_kind == "ASK_USER"
    assert result.response.audit_codes == ["PLAN_NEEDS_USER"]


@pytest.mark.asyncio
async def test_plan_modify_replacement_is_executed() -> None:
    app = CognitiveOrchestrator(
        selector=Selector(_action(_request())),
        dispatcher=Dispatcher(),
        plan_guardrail=ModifyPlanGuardrail(),  # type: ignore[arg-type]
    )

    result = await app.run(_event())

    assert result.response.response_kind == "ANSWER"
    assert result.response.message == "已收敛为只读知识回答"
