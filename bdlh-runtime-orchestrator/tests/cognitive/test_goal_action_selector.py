"""GoalActionSelector：needs_external 不默认归因金融。"""

from __future__ import annotations

import pytest

from bdlh_runtime.cognitive.contracts import CognitiveAction, CognitiveActionType, InputEvent
from bdlh_runtime.cognitive.goal_action_selector import GoalActionSelector, wants_finance_plugin
from bdlh_runtime.cognitive.goal_schema import (
    GoalSpec,
    SuccessCriterion,
    UnderstandEntities,
    UnderstandOutput,
)


class _Finance:
    async def select(self, event: InputEvent, *, understood=None) -> CognitiveAction:
        del understood
        return CognitiveAction(
            action_type=CognitiveActionType.ASK_USER,
            reason_code="FINANCE_HANDOFF",
            reason=f"finance:{event.message}",
        )


class _Respond:
    def answer(self, message: str) -> str:
        return f"chat:{message}"


def _understood(
    *,
    needs_external: bool = False,
    instruments: list[str] | None = None,
    topics: list[str] | None = None,
    missing: list[str] | None = None,
    needs_account: bool = False,
) -> UnderstandOutput:
    return UnderstandOutput(
        goals=[
            GoalSpec(
                goal_id="g1",
                objective="t",
                requested_topics=list(topics or []),
                needs_account=needs_account,
                success_criteria=[SuccessCriterion(criterion_id="c1", description="ok")],
            )
        ],
        entities=UnderstandEntities(instruments=list(instruments or [])),
        missing=list(missing or []),
        needs_external=needs_external,
    )


def _event(message: str, *, enabled_skills: frozenset[str] | None = None) -> InputEvent:
    return InputEvent(
        event_id="e1",
        user_id="u1",
        session_id="s1",
        message=message,
        enabled_skills=enabled_skills,
    )


@pytest.mark.asyncio
async def test_needs_external_web_only_stays_general_chat() -> None:
    """只要外部资料、无金融信号：即使 Skill 开着也不进金融插件。"""
    selector = GoalActionSelector(finance=_Finance(), respond=_Respond())
    action = await selector.select(
        _event("网上搜一下量子计算最新进展", enabled_skills=frozenset({"finance.stock-research"})),
        understood=_understood(needs_external=True, topics=["web_research"]),
    )
    assert action.reason_code == "GENERAL_CHAT"
    assert action.reason.startswith("chat:")


@pytest.mark.asyncio
async def test_finance_signal_with_skill_hands_off() -> None:
    selector = GoalActionSelector(finance=_Finance(), respond=_Respond())
    action = await selector.select(
        _event("600519今天怎么样", enabled_skills=frozenset({"finance.stock-research"})),
        understood=_understood(needs_external=True, instruments=["600519"]),
    )
    assert action.reason_code == "FINANCE_HANDOFF"


@pytest.mark.asyncio
async def test_finance_signal_without_skill_stays_chat() -> None:
    selector = GoalActionSelector(finance=_Finance(), respond=_Respond())
    action = await selector.select(
        _event("600519今天怎么样", enabled_skills=frozenset()),
        understood=_understood(needs_external=True, instruments=["600519"]),
    )
    assert action.reason_code == "GENERAL_CHAT_NO_FINANCE"


@pytest.mark.asyncio
async def test_missing_asks_user() -> None:
    selector = GoalActionSelector(finance=_Finance(), respond=_Respond())
    action = await selector.select(
        _event("帮我看看"),
        understood=_understood(missing=["objective"]),
    )
    assert action.action_type == CognitiveActionType.ASK_USER
    assert action.reason_code == "UNDERSTAND_MISSING"


def test_wants_finance_ignores_bare_web_research() -> None:
    assert not wants_finance_plugin(
        _understood(needs_external=True, topics=["web_research"]),
        "搜一下公开资料",
    )
    assert wants_finance_plugin(
        _understood(needs_external=True, instruments=["600519"], topics=["web_research"]),
        "搜一下600519相关新闻",
    )
