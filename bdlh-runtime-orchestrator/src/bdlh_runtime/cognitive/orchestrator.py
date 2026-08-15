"""Non-default M4 Cognitive orchestration with no concrete domain dependencies."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from bdlh_runtime.domains.contracts import DomainOutcome, DomainRequest

from .contracts import (
    ENABLED_ACTION_TYPES,
    CognitiveAction,
    CognitiveActionType,
    CognitiveState,
    CommunicationPlan,
    InputEvent,
    PublicResponse,
)
from bdlh_runtime.guardrails.contracts import GuardrailContext, GuardrailDecision
from bdlh_runtime.guardrails.policies import (
    DefaultActionGuardrail,
    DefaultDataQualityGuardrail,
    DefaultPlanGuardrail,
    DefaultResponseGuardrail,
)


class CognitiveActionSelector(Protocol):
    async def select(self, event: InputEvent) -> CognitiveAction: ...


class DomainDispatchPort(Protocol):
    """Injected domain-neutral port; the cognitive package does not own routing."""

    async def dispatch(self, request: DomainRequest) -> DomainOutcome: ...


class CognitiveExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: CognitiveState
    response: PublicResponse


class CognitiveOrchestrator:
    """A deterministic guarded pipeline, independently constructible from Root Graph."""

    def __init__(self, *, selector: CognitiveActionSelector, dispatcher: DomainDispatchPort) -> None:
        self._selector = selector
        self._dispatcher = dispatcher
        self._plan_guardrail = DefaultPlanGuardrail()
        self._action_guardrail = DefaultActionGuardrail()
        self._data_guardrail = DefaultDataQualityGuardrail()
        self._response_guardrail = DefaultResponseGuardrail()

    async def run(self, event: InputEvent) -> CognitiveExecution:
        context = GuardrailContext(
            run_id=event.run_id or event.event_id,
            authenticated_user_id=event.user_id,
            read_only=True,
            enabled_actions=frozenset(item.value for item in ENABLED_ACTION_TYPES),
        )
        action = await self._selector.select(event)
        state = CognitiveState(event=event, action=action)
        plan_result = self._plan_guardrail.evaluate_plan(action, context=context)
        if plan_result.decision != GuardrailDecision.ALLOW:
            return self._guardrail_exit(state, plan_result.audit_code or "PLAN_BLOCKED", plan_result.reasons)
        action_result = self._action_guardrail.evaluate_action(action, context=context)
        if action_result.decision != GuardrailDecision.ALLOW:
            return self._guardrail_exit(state, action_result.audit_code or "ACTION_BLOCKED", action_result.reasons)

        if action.action_type == CognitiveActionType.INVOKE_DOMAIN:
            assert action.domain_request is not None
            outcome = await self._dispatcher.dispatch(action.domain_request)
            state.domain_request = action.domain_request
            state.domain_outcome = outcome
            data_result = self._data_guardrail.evaluate_data_quality(outcome, context=context)
            if data_result.decision != GuardrailDecision.ALLOW:
                return self._guardrail_exit(state, data_result.audit_code or "DATA_BLOCKED", data_result.reasons, kind="LIMITED")
            plan = _domain_plan(outcome)
        elif action.action_type == CognitiveActionType.ASK_USER:
            plan = CommunicationPlan(response_kind="ASK_USER", summary=action.reason)
        else:
            plan = CommunicationPlan(response_kind="ANSWER", summary=action.reason)
        state.communication_plan = plan
        response = PublicResponse(
            response_kind=plan.response_kind,
            message=plan.summary,
            evidence_refs=plan.evidence_refs,
            limitations=plan.limitations,
            audit_codes=[action.reason_code],
        )
        response_result = self._response_guardrail.evaluate_response(response, context=context)
        if response_result.decision != GuardrailDecision.ALLOW:
            return self._guardrail_exit(state, response_result.audit_code or "RESPONSE_BLOCKED", response_result.reasons)
        state.public_events.append("response.ready")
        return CognitiveExecution(state=state, response=response)

    @staticmethod
    def _guardrail_exit(state: CognitiveState, code: str, reasons: list[str], *, kind: str = "BLOCKED") -> CognitiveExecution:
        state.error_codes.append(code)
        state.public_events.append("response.blocked")
        response = PublicResponse(response_kind=kind, message=reasons[0], limitations=reasons, audit_codes=[code])
        return CognitiveExecution(state=state, response=response)


def _domain_plan(outcome: object) -> CommunicationPlan:
    # Deliberately use only generic DomainOutcome fields; no finance-type knowledge leaks here.
    status = getattr(outcome, "status")
    limitations = list(getattr(outcome, "limitations"))
    facts = list(getattr(outcome, "established_facts"))
    findings = list(getattr(outcome, "findings"))
    evidence_refs = [ref for fact in facts for ref in fact.source_refs]
    evidence_refs.extend(ref for finding in findings for ref in finding.evidence_ids)
    evidence_refs = list(dict.fromkeys(evidence_refs))
    if status in {"LIMITED", "FAILED", "WAITING_USER"}:
        return CommunicationPlan(response_kind="LIMITED", summary="The domain result is limited.", evidence_refs=evidence_refs, limitations=limitations)
    return CommunicationPlan(response_kind="DOMAIN_RESULT", summary="The domain result is available.", evidence_refs=evidence_refs, limitations=limitations)
