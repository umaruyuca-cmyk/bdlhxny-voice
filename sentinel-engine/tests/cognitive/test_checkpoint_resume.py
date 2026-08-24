"""G1：Cognitive L0 Checkpoint 断点续跑。"""

from __future__ import annotations

from bdlh_runtime.cognitive.checkpoint import build_checkpoint
from bdlh_runtime.cognitive.contracts import (
    CognitiveAction,
    CognitiveActionType,
    CognitiveState,
    InputEvent,
)
from bdlh_runtime.cognitive.goal_schema import GoalSpec, SuccessCriterion
from bdlh_runtime.cognitive.orchestrator import CognitiveOrchestrator
from tests.helpers_understand import RuleBasedUnderstandModel


class _AskThenAnswerSelector:
    def __init__(self) -> None:
        self.calls = 0

    async def select(self, event: InputEvent, *, understood=None) -> CognitiveAction:
        del understood
        self.calls += 1
        if "600519" in event.message:
            return CognitiveAction(
                action_type=CognitiveActionType.RESPOND,
                reason_code="ANSWER",
                reason="已有标的",
            )
        return CognitiveAction(
            action_type=CognitiveActionType.ASK_USER,
            reason_code="NEED_SYMBOL",
            reason="缺标的",
        )


class _FakeDispatcher:
    async def dispatch(self, request):  # noqa: ANN001
        raise AssertionError(f"unexpected dispatch {request}")


async def test_ask_user_emits_non_empty_checkpoint() -> None:
    orchestrator = CognitiveOrchestrator(
        selector=_AskThenAnswerSelector(),
        dispatcher=_FakeDispatcher(),
        understand=RuleBasedUnderstandModel(),
    )
    first = await orchestrator.run(
        InputEvent(
            event_id="e1",
            run_id="r1",
            user_id="u1",
            session_id="s1",
            message="帮我看看走势",
        )
    )
    assert first.response.response_kind == "ASK_USER"
    assert first.checkpoint is not None
    assert first.checkpoint.checkpoint_id.startswith("cp:r1:")
    assert first.checkpoint.resume_cursor == "select"
    assert first.checkpoint.state.event.message == "帮我看看走势"


async def test_resume_from_checkpoint_skips_reunderstand_and_keeps_goals() -> None:
    selector = _AskThenAnswerSelector()
    understand = RuleBasedUnderstandModel()
    orchestrator = CognitiveOrchestrator(
        selector=selector,
        dispatcher=_FakeDispatcher(),
        understand=understand,
    )
    seed_goals = [
        GoalSpec(
            goal_id="g-seed",
            objective="保留的 Goal",
            success_criteria=[SuccessCriterion(criterion_id="c1", description="保留")],
        )
    ]
    checkpoint = build_checkpoint(
        run_id="r1",
        user_id="u1",
        state=CognitiveState(
            event=InputEvent(
                event_id="e1",
                run_id="r1",
                user_id="u1",
                session_id="s1",
                message="帮我看看走势",
            ),
            goals=seed_goals,
            needs_external=True,
        ),
        pause_reason="system_interrupt",
        resume_cursor="select",
    )
    resumed = await orchestrator.run(
        InputEvent(
            event_id="e2",
            run_id="r1",
            user_id="u1",
            session_id="s1",
            message="600519",
        ),
        checkpoint=checkpoint,
    )
    assert resumed.response.response_kind == "ANSWER"
    assert [goal.goal_id for goal in resumed.state.goals] == ["g-seed"]
    assert selector.calls == 1


class _OncePause:
    def __init__(self, after_calls: int) -> None:
        self._n = 0
        self._after = after_calls
        self._fired = False

    def __call__(self, run_id: str) -> bool:
        del run_id
        if self._fired:
            return False
        self._n += 1
        if self._n >= self._after:
            self._fired = True
            return True
        return False


class _InvokeSelector:
    def __init__(self, action: CognitiveAction) -> None:
        self.calls = 0
        self._action = action

    async def select(self, event: InputEvent, *, understood=None) -> CognitiveAction:
        del event, understood
        self.calls += 1
        return self._action


class _CompleteDispatcher:
    def __init__(self) -> None:
        self.calls = 0

    async def dispatch(self, request):  # noqa: ANN001
        from bdlh_runtime.domains.contracts import ConfidenceAssessment, DomainFact, DomainOutcome

        self.calls += 1
        return DomainOutcome(
            request_id=request.request_id,
            domain=request.domain,
            status="COMPLETE",
            established_facts=[
                DomainFact(fact_id="fact-1", statement="validated", source_refs=["source-1"], directness="DIRECT")
            ],
            confidence=ConfidenceAssessment(level="HIGH", reasons=["validated"], coverage_status="COMPLETE"),
        )


def _invoke_action() -> CognitiveAction:
    from bdlh_runtime.domains.contracts import DomainBudget, DomainOperation, DomainRequest

    return CognitiveAction(
        action_type=CognitiveActionType.INVOKE_DOMAIN,
        reason_code="DOMAIN_READ",
        reason="Read the requested result",
        domain_request=DomainRequest(
            request_id="request-1",
            domain="example",
            authenticated_user_id="u1",
            objective="Read a validated result",
            authorized_operations={DomainOperation.READ_PUBLIC_RESEARCH},
            budget=DomainBudget(tool_call_limit=1, runtime_seconds=5),
        ),
    )


def _domain_orchestrator(selector, dispatcher, pause_check):
    from bdlh_runtime.domains.contracts import DomainOperation

    return CognitiveOrchestrator(
        selector=selector,
        dispatcher=dispatcher,
        enabled_domains=frozenset({"example"}),
        authorized_operations=frozenset({DomainOperation.READ_PUBLIC_RESEARCH.value}),
        pause_check=pause_check,
        understand=RuleBasedUnderstandModel(),
    )


async def test_resume_from_dispatch_replays_pending_action_without_reselect() -> None:
    selector = _InvokeSelector(_invoke_action())
    dispatcher = _CompleteDispatcher()
    pause = _OncePause(after_calls=2)
    orchestrator = _domain_orchestrator(selector, dispatcher, pause)
    event = InputEvent(
        event_id="e1",
        run_id="r-dispatch",
        user_id="u1",
        session_id="s1",
        message="hello",
    )
    paused = await orchestrator.run(event)
    assert paused.state.public_events.count("run.paused") == 1
    assert "PAUSED_BY_USER" in paused.state.error_codes
    assert paused.checkpoint is not None
    assert paused.checkpoint.resume_cursor == "dispatch"
    assert selector.calls == 1
    assert dispatcher.calls == 0
    assert paused.state.domain_calls_used == 1

    resumed = await orchestrator.run(event, checkpoint=paused.checkpoint)
    assert "run.paused" not in resumed.state.public_events
    assert "PAUSED_BY_USER" not in resumed.state.error_codes
    assert selector.calls == 1
    assert dispatcher.calls == 1
    assert resumed.state.domain_calls_used == 1
    assert resumed.response.response_kind == "DOMAIN_RESULT"


async def test_resume_from_after_domain_does_not_dispatch_again() -> None:
    selector = _InvokeSelector(_invoke_action())
    dispatcher = _CompleteDispatcher()
    pause = _OncePause(after_calls=3)
    orchestrator = _domain_orchestrator(selector, dispatcher, pause)
    event = InputEvent(
        event_id="e1",
        run_id="r-after",
        user_id="u1",
        session_id="s1",
        message="hello",
    )
    paused = await orchestrator.run(event)
    assert paused.checkpoint is not None
    assert paused.checkpoint.resume_cursor == "after_domain"
    assert dispatcher.calls == 1
    assert paused.state.domain_calls_used == 1

    resumed = await orchestrator.run(event, checkpoint=paused.checkpoint)
    assert "run.paused" not in resumed.state.public_events
    assert "PAUSED_BY_USER" not in resumed.state.error_codes
    assert selector.calls == 1
    assert dispatcher.calls == 1
    assert resumed.state.domain_calls_used == 1
    assert resumed.response.response_kind == "DOMAIN_RESULT"

