"""Cognitive 编排内核；不依赖具体领域实现。"""

from __future__ import annotations

from collections.abc import Callable
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

from .checkpoint import CognitiveCheckpoint, build_checkpoint
from .contracts import (
    CognitiveAction,
    CognitiveActionSummary,
    CognitiveActionType,
    CognitiveState,
    CommunicationPlan,
    CommunicationSection,
    InputEvent,
    PublicResponse,
)
from .goal_schema import UnderstandOutput
from .policy import ActionPolicy, DefaultActionPolicy
from .understand import UnderstandModel


class CognitiveActionSelector(Protocol):
    async def select(
        self,
        event: InputEvent,
        *,
        understood: UnderstandOutput | None = None,
    ) -> CognitiveAction: ...


class CognitiveFastpath(Protocol):
    async def try_fastpath(self, event: InputEvent) -> CognitiveAction | None: ...


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
    checkpoint: CognitiveCheckpoint | None = None


class CognitiveOrchestrator:
    """四时点防护的确定性管线：快路径 → Understand → GoalAction → 可选 Domain 插件。"""

    def __init__(
        self,
        *,
        selector: CognitiveActionSelector,
        dispatcher: DomainDispatchPort,
        continuation: DomainContinuationPort | None = None,
        fastpath: CognitiveFastpath | None = None,
        action_policy: ActionPolicy | None = None,
        plan_guardrail: DefaultPlanGuardrail | None = None,
        action_guardrail: DefaultActionGuardrail | None = None,
        data_guardrail: DefaultDataQualityGuardrail | None = None,
        response_guardrail: DefaultResponseGuardrail | None = None,
        enabled_domains: frozenset[str] = frozenset(),
        authorized_operations: frozenset[str] = frozenset(),
        authorized_capabilities: frozenset[str] = frozenset(),
        observer: CognitiveExecutionObserver | None = None,
        max_domain_steps: int = 2,
        pause_check: Callable[[str], bool] | None = None,
        understand: UnderstandModel,
    ) -> None:
        if max_domain_steps < 1:
            raise ValueError("max_domain_steps must be positive")
        if understand is None:
            raise ValueError("understand is required")
        self._selector = selector
        self._fastpath = fastpath
        self._dispatcher = dispatcher
        self._continuation = continuation
        self._action_policy = action_policy or DefaultActionPolicy()
        self._max_domain_steps = max_domain_steps
        self._enabled_domains = enabled_domains
        self._authorized_operations = authorized_operations
        self._authorized_capabilities = authorized_capabilities
        self._observer = observer or NoopCognitiveExecutionObserver()
        self._plan_guardrail = plan_guardrail or DefaultPlanGuardrail()
        self._action_guardrail = action_guardrail or DefaultActionGuardrail()
        self._data_guardrail = data_guardrail or DefaultDataQualityGuardrail()
        self._response_guardrail = response_guardrail or DefaultResponseGuardrail()
        self._pause_check = pause_check
        self._understand = understand

    async def run(
        self,
        event: InputEvent,
        *,
        observer: CognitiveExecutionObserver | None = None,
        checkpoint: CognitiveCheckpoint | None = None,
    ) -> CognitiveExecution:
        execution_observer = observer or self._observer
        context = GuardrailContext(
            run_id=event.run_id or event.event_id,
            authenticated_user_id=event.user_id,
            read_only=True,
            authorized_capabilities=self._authorized_capabilities,
            enabled_domains=self._enabled_domains,
            authorized_operations=self._authorized_operations,
            enabled_actions=frozenset(item.value for item in self._action_policy.enabled_actions),
        )
        from .goal_coverage import backfill_criteria

        if checkpoint is not None:
            state = checkpoint.state.model_copy(deep=True)
            state.event = event
            state.public_events = [item for item in state.public_events if item != "run.paused"]
            state.error_codes = [item for item in state.error_codes if item != "PAUSED_BY_USER"]
            if checkpoint.resume_cursor == "dispatch" and checkpoint.pending_action is not None:
                action = checkpoint.pending_action
                return await self._action_loop(
                    event=event,
                    state=state,
                    action=action,
                    context=context,
                    execution_observer=execution_observer,
                    start_at_dispatch=True,
                )
            if checkpoint.resume_cursor == "after_domain" and checkpoint.last_outcome is not None:
                outcome = DomainOutcome.model_validate(checkpoint.last_outcome)
                return await self._continue_from_outcome(
                    event=event,
                    state=state,
                    outcome=outcome,
                    context=context,
                    execution_observer=execution_observer,
                    prior_action=checkpoint.pending_action,
                )
            # select：保留 goals，仅用新消息重选行动
            action = await self._select_action(event, understood=None)
            if state.goals:
                action = action.model_copy(
                    update={"related_goal_ids": [goal.goal_id for goal in state.goals]}
                )
            return await self._action_loop(
                event=event,
                state=state,
                action=action,
                context=context,
                execution_observer=execution_observer,
            )

        fastpath_action = await self._try_fastpath(event)
        if fastpath_action is not None:
            state = CognitiveState(event=event, goals=[], needs_external=False)
            return await self._action_loop(
                event=event,
                state=state,
                action=fastpath_action,
                context=context,
                execution_observer=execution_observer,
            )

        understood = await self._understand.understand(event.message)
        allowed_names = sorted(self._authorized_capabilities)
        goals = backfill_criteria(list(understood.goals), allowed_names)
        state = CognitiveState(
            event=event,
            goals=goals,
            needs_external=understood.needs_external,
        )
        action = await self._select_action(event, understood=understood)
        if state.goals:
            action = action.model_copy(
                update={"related_goal_ids": [goal.goal_id for goal in state.goals]}
            )
        return await self._action_loop(
            event=event,
            state=state,
            action=action,
            context=context,
            execution_observer=execution_observer,
        )

    async def _try_fastpath(self, event: InputEvent) -> CognitiveAction | None:
        if self._fastpath is None:
            return None
        return await self._fastpath.try_fastpath(event)

    async def _select_action(
        self,
        event: InputEvent,
        *,
        understood: UnderstandOutput | None,
    ) -> CognitiveAction:
        # 恢复选择：先尝试快路径，再 Understand 后交给 GoalActionSelector
        if understood is None:
            fastpath_action = await self._try_fastpath(event)
            if fastpath_action is not None:
                return fastpath_action
            understood = await self._understand.understand(event.message)
        return await self._selector.select(event, understood=understood)

    async def _action_loop(
        self,
        *,
        event: InputEvent,
        state: CognitiveState,
        action: CognitiveAction,
        context: GuardrailContext,
        execution_observer: CognitiveExecutionObserver,
        start_at_dispatch: bool = False,
    ) -> CognitiveExecution:
        for step in range(self._max_domain_steps + 1):
            if not start_at_dispatch:
                if self._should_pause(event):
                    return self._paused_exit(
                        state,
                        resume_cursor="select",
                        pending_action=None,
                    )
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
                requested_runtime_seconds = state.requested_runtime_seconds + request.budget.runtime_seconds
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
                if self._should_pause(event):
                    return self._paused_exit(
                        state,
                        resume_cursor="dispatch",
                        pending_action=action,
                    )
            else:
                start_at_dispatch = False
                assert action.domain_request is not None
                request = action.domain_request

            execution_observer.on_domain_request(request)
            outcome = await self._dispatcher.dispatch(request)
            if self._should_pause(event):
                return self._paused_exit(
                    state,
                    resume_cursor="after_domain",
                    pending_action=action,
                    last_outcome=outcome.model_dump(mode="json"),
                )
            continued = await self._continue_from_outcome(
                event=event,
                state=state,
                outcome=outcome,
                context=context,
                execution_observer=execution_observer,
                prior_action=action,
                return_next_action=True,
            )
            if isinstance(continued, CognitiveAction):
                action = continued
                continue
            return continued

        raise AssertionError("unreachable")

    async def _continue_from_outcome(
        self,
        *,
        event: InputEvent,
        state: CognitiveState,
        outcome: DomainOutcome,
        context: GuardrailContext,
        execution_observer: CognitiveExecutionObserver,
        prior_action: CognitiveAction | None,
        return_next_action: bool = False,
    ) -> CognitiveExecution | CognitiveAction:
        outcome_callback = getattr(execution_observer, "on_domain_outcome", None)
        if callable(outcome_callback):
            outcome_callback(outcome)
        if outcome.request_id not in state.domain_outcome_refs:
            state.domain_outcome_refs.append(outcome.request_id)
        outcome_before_communication = outcome.model_dump(mode="json")

        data_result = self._data_guardrail.evaluate_data_quality(outcome, context=context)
        if data_result.decision != GuardrailDecision.ALLOW:
            return self._guardrail_exit(state, data_result, kind="LIMITED")

        # G6 / ADR-014：领域或 Deep Research 超预算 → 系统截断 Pause（可恢复），禁止假 COMPLETE
        if _is_budget_exhaustion(outcome):
            return self._budget_pause_exit(
                state,
                outcome=outcome,
                pending_action=prior_action,
            )

        state.goals = _refresh_goal_coverage(
            state.goals,
            outcome=outcome,
            allowed=sorted(self._authorized_capabilities),
        )

        continuation = None
        if self._continuation is not None:
            continuation = await self._continuation.continue_after(event=event, outcome=outcome)
        if isinstance(continuation, CognitiveAction):
            action = continuation
            if state.goals:
                action = action.model_copy(
                    update={"related_goal_ids": [goal.goal_id for goal in state.goals]}
                )
            if return_next_action:
                return action
            return await self._action_loop(
                event=event,
                state=state,
                action=action,
                context=context,
                execution_observer=execution_observer,
            )
        plan = continuation if isinstance(continuation, CommunicationPlan) else _domain_plan(outcome)
        if outcome.model_dump(mode="json") != outcome_before_communication:
            return self._guardrail_exit_code(
                state,
                "DOMAIN_OUTCOME_MUTATED",
                ["表达阶段不得修改领域结果"],
            )
        allowed_refs = set(
            _collect_string_refs(
                outcome_before_communication,
                {"source_refs", "evidence_refs", "evidence_ids", "calculation_ids"},
            )
        )
        if not set(plan.evidence_refs).issubset(allowed_refs):
            return self._guardrail_exit_code(
                state,
                "RESPONSE_EVIDENCE_NOT_TRACEABLE",
                ["表达计划包含领域结果中不存在的证据引用"],
            )
        plan = _apply_goal_coverage_gate(plan, state.goals, needs_external=state.needs_external)
        audit = prior_action.reason_code if prior_action is not None else "DOMAIN_RESULT"
        return self._finalize(state, plan, context=context, audit_code=audit)

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
            response.audit_codes = list(
                dict.fromkeys(response.audit_codes + [result.audit_code or "RESPONSE_MODIFIED"])
            )
        elif result.decision != GuardrailDecision.ALLOW:
            return self._guardrail_exit(state, result)
        state.public_events.append("response.ready")
        checkpoint = None
        if response.response_kind == "ASK_USER":
            checkpoint = build_checkpoint(
                run_id=str(state.event.run_id or state.event.event_id),
                user_id=state.event.user_id,
                state=state,
                pause_reason="system_interrupt",
                resume_cursor="select",
                original_message=state.event.message,
            )
        return CognitiveExecution(state=state, response=response, checkpoint=checkpoint)

    def _should_pause(self, event: InputEvent) -> bool:
        if self._pause_check is None:
            return False
        run_id = str(event.run_id or event.event_id or "").strip()
        return bool(run_id) and bool(self._pause_check(run_id))

    def _paused_exit(
        self,
        state: CognitiveState,
        *,
        resume_cursor: str = "select",
        pending_action: CognitiveAction | None = None,
        last_outcome: dict | None = None,
    ) -> CognitiveExecution:
        state.public_events.append("run.paused")
        state.error_codes.append("PAUSED_BY_USER")
        checkpoint = build_checkpoint(
            run_id=str(state.event.run_id or state.event.event_id),
            user_id=state.event.user_id,
            state=state,
            pause_reason="user_pause",
            resume_cursor=resume_cursor,  # type: ignore[arg-type]
            pending_action=pending_action,
            last_outcome=last_outcome,
            original_message=state.event.message,
        )
        return CognitiveExecution(
            state=state,
            response=PublicResponse(
                response_kind="ASK_USER",
                response_structure="CLARIFICATION",
                message="已按你的操作暂停。回复「继续」可接着刚才的分析，或直接提出新的问题。",
                next_steps=["继续", "换一个新问题"],
                audit_codes=["PAUSED_BY_USER"],
            ),
            checkpoint=checkpoint,
        )

    def _budget_pause_exit(
        self,
        state: CognitiveState,
        *,
        outcome: DomainOutcome,
        pending_action: CognitiveAction | None,
    ) -> CognitiveExecution:
        state.public_events.append("run.paused")
        state.error_codes.append("RUN_BUDGET_EXCEEDED")
        codes = [item.code for item in outcome.errors]
        message = (
            outcome.errors[0].message
            if outcome.errors
            else "本轮研究预算已用尽，已安全暂停；回复「继续」可从断点恢复。"
        )
        checkpoint = build_checkpoint(
            run_id=str(state.event.run_id or state.event.event_id),
            user_id=state.event.user_id,
            state=state,
            pause_reason="system_interrupt",
            resume_cursor="after_domain",
            pending_action=pending_action,
            last_outcome=outcome.model_dump(mode="json"),
            original_message=state.event.message,
        )
        return CognitiveExecution(
            state=state,
            response=PublicResponse(
                response_kind="ASK_USER",
                response_structure="CLARIFICATION",
                message=message,
                limitations=list(outcome.limitations),
                next_steps=["继续", "换一个新问题"],
                audit_codes=list(dict.fromkeys(["RUN_BUDGET_EXCEEDED", *codes])),
            ),
            checkpoint=checkpoint,
        )

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
        return CognitiveOrchestrator._guardrail_exit_code(
            state,
            code,
            result.reasons,
            kind=kind,
            rule_ids=list(result.rule_ids),
        )

    @staticmethod
    def _guardrail_exit_code(
        state: CognitiveState,
        code: str,
        reasons: list[str],
        *,
        kind: str = "BLOCKED",
        rule_ids: list[str] | None = None,
    ) -> CognitiveExecution:
        state.error_codes.append(code)
        state.public_events.append("response.blocked")
        state.public_events.append("guardrail.blocked")
        message = reasons[0] if reasons else "请求已被安全策略阻断"
        response = PublicResponse(
            response_kind=kind,
            response_structure=("CAPABILITY_NOTICE" if kind == "CAPABILITY_NOT_ENABLED" else "SAFETY_BLOCK"),
            message=message,
            limitations=reasons,
            audit_codes=[code],
            rule_ids=list(rule_ids or []),
        )
        return CognitiveExecution(state=state, response=response)


def _action_plan(action: CognitiveAction) -> CommunicationPlan:
    if action.action_type == CognitiveActionType.ASK_USER:
        return CommunicationPlan(
            response_kind="ASK_USER",
            response_structure="CLARIFICATION",
            summary=action.reason,
            sections=[
                CommunicationSection(
                    section_type="NEXT_STEPS",
                    title="需要你确认",
                    items=[action.reason],
                )
            ],
            next_steps=["请补充问题中要求的信息后继续。"],
        )
    return CommunicationPlan(
        response_kind="ANSWER",
        response_structure="KNOWLEDGE",
        summary=action.reason,
        sections=[CommunicationSection(section_type="SUMMARY", title="说明", items=[action.reason])],
    )


def _domain_plan(outcome: DomainOutcome) -> CommunicationPlan:
    """只读取通用契约及递归公开引用，不解释任何具体领域枚举。"""
    dumped = outcome.model_dump(mode="json")
    evidence_refs = _collect_string_refs(dumped, {"source_refs", "evidence_refs", "evidence_ids", "calculation_ids"})
    statements = _collect_values(dumped, {"statement", "headline", "description"})
    data_times = _collect_values(dumped, {"data_time", "source_time", "trade_date", "retrieved_at", "published_at"})
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
            sections=sections
            + [
                CommunicationSection(
                    section_type="NEXT_STEPS",
                    title="需要你确认",
                    items=[decision.question],
                )
            ],
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
            sections.append(
                CommunicationSection(
                    section_type=section_type,
                    title=title,
                    items=items,
                )
            )
    return sections


def _outcome_observations(outcome: DomainOutcome) -> list[dict]:
    found: list[dict] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if "observation_id" in node and "capability" in node:
                found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(outcome.model_dump(mode="json"))
    return found


def _refresh_goal_coverage(goals: list, *, outcome: DomainOutcome, allowed: list[str]):
    from .goal_coverage import evaluate_goals
    from .goal_schema import GoalSpec

    if not goals:
        return goals
    typed = [goal if isinstance(goal, GoalSpec) else GoalSpec.model_validate(goal) for goal in goals]
    observations = _outcome_observations(outcome)
    updated = evaluate_goals(typed, observations, allowed)
    # 当前 DomainOutcome 未必携带统一 Observation 信封；COMPLETE 时结算仍为 PENDING 的 Goal
    if outcome.status == "COMPLETE":
        settled = []
        for goal in updated:
            if goal.status == "PENDING":
                settled.append(goal.model_copy(update={"status": "COVERED"}))
            else:
                settled.append(goal)
        return settled
    return updated


def _is_budget_exhaustion(outcome: DomainOutcome) -> bool:
    """领域超预算或 Deep Research 预算耗尽 → 走 ADR-014 系统 Pause。"""
    budget_codes = {
        "BUDGET_EXHAUSTED",
        "RUNTIME_BUDGET_EXHAUSTED",
        "DEEP_RESEARCH_BUDGET_EXHAUSTED",
        "RUN_BUDGET_EXCEEDED",
    }
    if any(item.code in budget_codes for item in outcome.errors):
        return True
    return any(
        "DEEP_RESEARCH_BUDGET_EXHAUSTED" in str(item) or "budget exhausted" in str(item).lower()
        for item in outcome.limitations
    )


def _apply_goal_coverage_gate(plan: CommunicationPlan, goals: list, *, needs_external: bool) -> CommunicationPlan:
    from .goal_coverage import all_goals_settled
    from .goal_schema import GoalSpec

    if not needs_external or not goals:
        return plan
    typed = [goal if isinstance(goal, GoalSpec) else GoalSpec.model_validate(goal) for goal in goals]
    if all_goals_settled(typed):
        return plan
    pending = [goal.goal_id for goal in typed if goal.status == "PENDING"]
    if not pending:
        return plan
    limitation = f"Goals still pending coverage: {', '.join(pending)}"
    limitations = list(dict.fromkeys([*plan.limitations, limitation]))
    # 硬降级：仅当表达为“完成态”却仍有 PENDING Goal
    if plan.response_kind in {"DOMAIN_RESULT", "ANSWER"}:
        return plan.model_copy(
            update={
                "response_kind": "LIMITED",
                "limitations": limitations,
                "summary": f"{plan.summary}（目标尚未完全覆盖，结果标记为有限）",
            }
        )
    return plan.model_copy(update={"limitations": limitations})
