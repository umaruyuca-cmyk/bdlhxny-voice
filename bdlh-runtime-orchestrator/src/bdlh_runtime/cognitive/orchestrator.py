"""独立、非默认的 M4 Cognitive 编排；内核不依赖具体领域。"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from bdlh_runtime.domains.contracts import DomainOutcome, DomainRequest
from bdlh_runtime.guardrails.contracts import GuardrailContext, GuardrailDecision, GuardrailResult
from bdlh_runtime.guardrails.policies import (
    DefaultActionGuardrail,
    DefaultDataQualityGuardrail,
    DefaultPlanGuardrail,
    DefaultResponseGuardrail,
)

from .contracts import (
    CognitiveAction,
    CognitiveActionSummary,
    CognitiveActionType,
    CognitiveState,
    CommunicationSection,
    CommunicationPlan,
    InputEvent,
    PublicResponse,
)
from .policy import ActionPolicy, DefaultActionPolicy


class CognitiveActionSelector(Protocol):
    async def select(self, event: InputEvent) -> CognitiveAction: ...


class DomainDispatchPort(Protocol):
    async def dispatch(self, request: DomainRequest) -> DomainOutcome: ...


class DomainContinuationPort(Protocol):
    """领域扩展可在一次受控结果后请求下一步行动或给出表达计划。"""

    async def continue_after(
        self, *, event: InputEvent, outcome: DomainOutcome
    ) -> CognitiveAction | CommunicationPlan | None: ...


class CognitiveExecutionObserver(Protocol):
    def on_domain_request(self, request: DomainRequest) -> None: ...
    def on_domain_outcome(self, outcome: DomainOutcome) -> None: ...


class NoopCognitiveExecutionObserver:
    def on_domain_request(self, request: DomainRequest) -> None:
        del request

    def on_domain_outcome(self, outcome: DomainOutcome) -> None:
        del outcome


class CognitiveExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: CognitiveState
    response: PublicResponse


class CognitiveOrchestrator:
    """四时点防护的确定性管线，可独立于旧 Root Graph 装配。"""

    def __init__(
        self,
        *,
        selector: CognitiveActionSelector,
        dispatcher: DomainDispatchPort,
        continuation: DomainContinuationPort | None = None,
        action_policy: ActionPolicy | None = None,
        plan_guardrail: DefaultPlanGuardrail | None = None,
        action_guardrail: DefaultActionGuardrail | None = None,
        data_guardrail: DefaultDataQualityGuardrail | None = None,
        response_guardrail: DefaultResponseGuardrail | None = None,
        enabled_domains: frozenset[str] = frozenset(),
        authorized_operations: frozenset[str] = frozenset(),
        observer: CognitiveExecutionObserver | None = None,
        max_domain_steps: int = 2,
    ) -> None:
        if max_domain_steps < 1:
            raise ValueError("max_domain_steps must be positive")
        self._selector = selector
        self._dispatcher = dispatcher
        self._continuation = continuation
        self._action_policy = action_policy or DefaultActionPolicy()
        self._max_domain_steps = max_domain_steps
        self._enabled_domains = enabled_domains
        self._authorized_operations = authorized_operations
        self._observer = observer or NoopCognitiveExecutionObserver()
        self._plan_guardrail = plan_guardrail or DefaultPlanGuardrail()
        self._action_guardrail = action_guardrail or DefaultActionGuardrail()
        self._data_guardrail = data_guardrail or DefaultDataQualityGuardrail()
        self._response_guardrail = response_guardrail or DefaultResponseGuardrail()

    async def run(
        self,
        event: InputEvent,
        *,
        observer: CognitiveExecutionObserver | None = None,
    ) -> CognitiveExecution:
        execution_observer = observer or self._observer
        context = GuardrailContext(
            run_id=event.run_id or event.event_id,
            authenticated_user_id=event.user_id,
            read_only=True,
            enabled_domains=self._enabled_domains,
            authorized_operations=self._authorized_operations,
            enabled_actions=frozenset(
                item.value for item in self._action_policy.enabled_actions
            ),
        )
        state = CognitiveState(event=event)
        action = await self._selector.select(event)

        for step in range(self._max_domain_steps + 1):
            state.action = CognitiveActionSummary.from_action(action)
            state.action_history.append(state.action)
            policy_result = self._action_policy.evaluate(action)
            if policy_result.decision == "REJECTED":
                return self._guardrail_exit_code(
                    state,
                    policy_result.audit_code or "ACTION_POLICY_REJECTED",
                    [policy_result.public_reason or "该行动当前未启用"],
                    kind="CAPABILITY_NOT_ENABLED",
                )
            plan_result = self._plan_guardrail.evaluate_plan(action, context=context)
            if plan_result.decision == GuardrailDecision.MODIFY:
                assert plan_result.replacement is not None
                action = plan_result.replacement
                state.action = CognitiveActionSummary.from_action(action)
            elif plan_result.decision != GuardrailDecision.ALLOW:
                return self._guardrail_exit(state, plan_result, action=action)
            action_result = self._action_guardrail.evaluate_action(action, context=context)
            if action_result.decision == GuardrailDecision.MODIFY:
                assert action_result.replacement is not None
                action = action_result.replacement
                state.action = CognitiveActionSummary.from_action(action)
            elif action_result.decision != GuardrailDecision.ALLOW:
                return self._guardrail_exit(state, action_result, action=action)

            if action.action_type != CognitiveActionType.INVOKE_DOMAIN:
                plan = _action_plan(action)
                return self._finalize(state, plan, context=context, audit_code=action.reason_code)

            if step >= self._max_domain_steps:
                return self._guardrail_exit_code(
                    state,
                    "COGNITIVE_STEP_LIMIT_EXCEEDED",
                    ["本轮领域调用步骤已达到上限"],
                )
            assert action.domain_request is not None
            request = action.domain_request
            requested_tool_calls = state.requested_tool_calls + request.budget.tool_call_limit
            requested_runtime_seconds = (
                state.requested_runtime_seconds + request.budget.runtime_seconds
            )
            if (
                requested_tool_calls > context.max_tool_calls
                or requested_runtime_seconds > context.max_runtime_seconds
            ):
                return self._guardrail_exit_code(
                    state,
                    "RUN_BUDGET_EXCEEDED",
                    ["本轮累计领域调用预算超过允许上限"],
                )
            state.requested_tool_calls = requested_tool_calls
            state.requested_runtime_seconds = requested_runtime_seconds
            state.domain_calls_used += 1
            state.domain_request_refs.append(request.request_id)
            execution_observer.on_domain_request(request)
            outcome = await self._dispatcher.dispatch(request)
            outcome_callback = getattr(execution_observer, "on_domain_outcome", None)
            if callable(outcome_callback):
                outcome_callback(outcome)
            state.domain_outcome_refs.append(outcome.request_id)
            outcome_before_communication = outcome.model_dump(mode="json")

            data_result = self._data_guardrail.evaluate_data_quality(outcome, context=context)
            if data_result.decision != GuardrailDecision.ALLOW:
                return self._guardrail_exit(state, data_result, kind="LIMITED")

            continuation = None
            if self._continuation is not None:
                continuation = await self._continuation.continue_after(event=event, outcome=outcome)
            if isinstance(continuation, CognitiveAction):
                action = continuation
                continue
            plan = continuation if isinstance(continuation, CommunicationPlan) else _domain_plan(outcome)
            if outcome.model_dump(mode="json") != outcome_before_communication:
                return self._guardrail_exit_code(
                    state,
                    "DOMAIN_OUTCOME_MUTATED",
                    ["表达阶段不得修改领域结果"],
                )
            allowed_refs = set(_collect_string_refs(
                outcome_before_communication,
                {"source_refs", "evidence_refs", "evidence_ids", "calculation_ids"},
            ))
            if not set(plan.evidence_refs).issubset(allowed_refs):
                return self._guardrail_exit_code(
                    state,
                    "RESPONSE_EVIDENCE_NOT_TRACEABLE",
                    ["表达计划包含领域结果中不存在的证据引用"],
                )
            return self._finalize(state, plan, context=context, audit_code=action.reason_code)

        raise AssertionError("unreachable")

    def _finalize(
        self,
        state: CognitiveState,
        plan: CommunicationPlan,
        *,
        context: GuardrailContext,
        audit_code: str,
    ) -> CognitiveExecution:
        state.communication_plan = plan
        response = PublicResponse(
            response_kind=plan.response_kind,
            response_structure=plan.response_structure,
            message=plan.summary,
            sections=plan.sections,
            evidence_refs=plan.evidence_refs,
            data_times=plan.data_times,
            limitations=plan.limitations,
            risk_disclosures=plan.risk_disclosures,
            next_steps=plan.next_steps,
            audit_codes=[audit_code],
        )
        result = self._response_guardrail.evaluate_response(response, context=context)
        if result.decision == GuardrailDecision.MODIFY:
            assert result.replacement is not None
            response = result.replacement
            response.audit_codes = list(dict.fromkeys(response.audit_codes + [result.audit_code or "RESPONSE_MODIFIED"]))
        elif result.decision != GuardrailDecision.ALLOW:
            return self._guardrail_exit(state, result)
        state.public_events.append("response.ready")
        return CognitiveExecution(state=state, response=response)

    @staticmethod
    def _guardrail_exit(
        state: CognitiveState,
        result: GuardrailResult[object],
        *,
        action: CognitiveAction | None = None,
        kind: str = "BLOCKED",
    ) -> CognitiveExecution:
        code = result.audit_code or "GUARDRAIL_BLOCKED"
        if code == "ACTION_NOT_ENABLED":
            kind = "CAPABILITY_NOT_ENABLED"
        if result.decision == GuardrailDecision.ASK_USER:
            kind = "ASK_USER"
        return CognitiveOrchestrator._guardrail_exit_code(state, code, result.reasons, kind=kind)

    @staticmethod
    def _guardrail_exit_code(
        state: CognitiveState,
        code: str,
        reasons: list[str],
        *,
        kind: str = "BLOCKED",
    ) -> CognitiveExecution:
        state.error_codes.append(code)
        state.public_events.append("response.blocked")
        message = reasons[0] if reasons else "请求已被安全策略阻断"
        response = PublicResponse(
            response_kind=kind,
            response_structure=(
                "CAPABILITY_NOTICE" if kind == "CAPABILITY_NOT_ENABLED" else "SAFETY_BLOCK"
            ),
            message=message,
            limitations=reasons,
            audit_codes=[code],
        )
        return CognitiveExecution(state=state, response=response)


def _action_plan(action: CognitiveAction) -> CommunicationPlan:
    if action.action_type == CognitiveActionType.ASK_USER:
        return CommunicationPlan(
            response_kind="ASK_USER",
            response_structure="CLARIFICATION",
            summary=action.reason,
            sections=[CommunicationSection(
                section_type="NEXT_STEPS",
                title="需要你确认",
                items=[action.reason],
            )],
            next_steps=["请补充问题中要求的信息后继续。"],
        )
    return CommunicationPlan(
        response_kind="ANSWER",
        response_structure="KNOWLEDGE",
        summary=action.reason,
        sections=[CommunicationSection(
            section_type="SUMMARY", title="说明", items=[action.reason]
        )],
    )


def _domain_plan(outcome: DomainOutcome) -> CommunicationPlan:
    """只读取通用契约及递归公开引用，不解释任何具体领域枚举。"""
    dumped = outcome.model_dump(mode="json")
    evidence_refs = _collect_string_refs(dumped, {"source_refs", "evidence_refs", "evidence_ids", "calculation_ids"})
    statements = _collect_values(dumped, {"statement", "headline", "description"})
    data_times = _collect_values(
        dumped, {"data_time", "source_time", "trade_date", "retrieved_at", "published_at"}
    )
    limitations = list(dict.fromkeys(outcome.limitations))
    risk_disclosures = _collect_values(dumped.get("risks", []), {"description"})
    next_steps = _collect_values(dumped.get("suggested_followups", []), {"description"})
    fact_statements = _collect_values(dumped.get("established_facts", []), {"statement"})
    finding_statements = _collect_values(dumped.get("findings", []), {"statement"})
    sections = _sections(
        facts=fact_statements,
        findings=finding_statements,
        risks=risk_disclosures,
        limitations=limitations,
        next_steps=next_steps,
    )
    if outcome.status == "WAITING_USER" and outcome.required_user_decisions:
        decision = outcome.required_user_decisions[0]
        return CommunicationPlan(
            response_kind="ASK_USER",
            response_structure="CLARIFICATION",
            summary=decision.question,
            sections=sections + [CommunicationSection(
                section_type="NEXT_STEPS",
                title="需要你确认",
                items=[decision.question],
            )],
            required_fields=[decision.decision_id],
            evidence_refs=evidence_refs,
            data_times=data_times,
            limitations=limitations,
            risk_disclosures=risk_disclosures,
            next_steps=[decision.question],
        )
    if outcome.status in {"LIMITED", "PARTIAL"}:
        summary = statements[0] if statements else "领域结果可用，但信息覆盖不完整。"
        return CommunicationPlan(
            response_kind="LIMITED",
            response_structure="RESEARCH",
            summary=summary,
            sections=sections,
            evidence_refs=evidence_refs,
            data_times=data_times,
            limitations=limitations or ["领域结果覆盖不完整"],
            risk_disclosures=risk_disclosures,
            next_steps=next_steps,
        )
    summary = statements[0] if statements else "领域结果已完成。"
    return CommunicationPlan(
        response_kind="DOMAIN_RESULT",
        response_structure="RESEARCH",
        summary=summary,
        sections=sections,
        evidence_refs=evidence_refs,
        data_times=data_times,
        limitations=limitations,
        risk_disclosures=risk_disclosures,
        next_steps=next_steps,
    )


def _collect_string_refs(value: object, keys: set[str]) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, list):
                refs.extend(str(ref) for ref in item if isinstance(ref, str) and ref)
            refs.extend(_collect_string_refs(item, keys))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_collect_string_refs(item, keys))
    return list(dict.fromkeys(refs))


def _collect_values(value: object, keys: set[str]) -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, str) and item:
                values.append(item)
            values.extend(_collect_values(item, keys))
    elif isinstance(value, list):
        for item in value:
            values.extend(_collect_values(item, keys))
    return list(dict.fromkeys(values))


def _sections(
    *,
    facts: list[str],
    findings: list[str],
    risks: list[str],
    limitations: list[str],
    next_steps: list[str],
) -> list[CommunicationSection]:
    sections: list[CommunicationSection] = []
    for section_type, title, items in (
        ("FACTS", "已确认事实", facts),
        ("FINDINGS", "研究结论", findings),
        ("RISKS", "风险", risks),
        ("LIMITATIONS", "限制", limitations),
        ("NEXT_STEPS", "下一步", next_steps),
    ):
        if items:
            sections.append(CommunicationSection(
                section_type=section_type,
                title=title,
                items=items,
            ))
    return sections
