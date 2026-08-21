"""G1：Cognitive L0 Checkpoint 断点续跑。"""

from __future__ import annotations

from bdlh_runtime.cognitive.checkpoint import build_checkpoint
from bdlh_runtime.cognitive.contracts import (
    CognitiveAction,
    CognitiveActionType,
    CognitiveState,
    InputEvent,
    PublicResponse,
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
    assert first.state.goals


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
