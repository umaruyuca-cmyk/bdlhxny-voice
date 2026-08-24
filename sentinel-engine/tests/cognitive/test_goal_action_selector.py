"""GoalActionSelector：LLM 输出 action 则按域调度；否则 Agent 直接回答。"""

from __future__ import annotations

import pytest

from bdlh_runtime.cognitive.contracts import (
    CognitiveAction,
    CognitiveActionType,
    InputEvent,
    InputEventType,
)
from bdlh_runtime.cognitive.goal_action_selector import GoalActionSelector
from bdlh_runtime.cognitive.goal_schema import (
    ActionSpec,
    GoalSpec,
    SuccessCriterion,
    UnderstandEntities,
    UnderstandOutput,
)
from bdlh_runtime.cognitive.plugin_gates import SkillCatalog, SkillToolSpec
from tests.helpers_skill_catalog import DEMO_SKILL_CATALOG


class _Finance:
    async def select(self, event: InputEvent, *, understood=None) -> CognitiveAction:
        del understood
        return CognitiveAction(
            action_type=CognitiveActionType.ASK_USER,
            reason_code="FINANCE_HANDOFF",
            reason=f"finance:{event.message}",
        )


class _Weather:
    async def select(self, event: InputEvent, *, understood=None) -> CognitiveAction:
        del understood
        return CognitiveAction(
            action_type=CognitiveActionType.RESPOND,
            reason_code="WEATHER_HANDOFF",
            reason=f"weather:{event.message}",
        )


class _Respond:
    def answer(self, message: str) -> str:
        return f"chat:{message}"


def _selector(**handlers) -> GoalActionSelector:
    return GoalActionSelector(
        handlers=handlers or {"finance": _Finance()},
        catalog=DEMO_SKILL_CATALOG,
        respond=_Respond(),
    )


def _understood(
    *,
    needs_external: bool = False,
    instruments: list[str] | None = None,
    topics: list[str] | None = None,
    missing: list[str] | None = None,
    needs_account: bool = False,
    action: ActionSpec | None = None,
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
        action=action,
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
async def test_no_action_stays_agent_reply_even_with_skills() -> None:
    selector = _selector()
    action = await selector.select(
        _event("网上搜一下量子计算最新进展", enabled_skills=frozenset({"finance.stock-research"})),
        understood=_understood(needs_external=True, topics=["web_research"]),
    )
    assert action.reason_code == "RESPOND"
    assert action.reason.startswith("chat:")


@pytest.mark.asyncio
async def test_action_dispatches_to_handler() -> None:
    selector = _selector()
    action = await selector.select(
        _event("600519今天怎么样", enabled_skills=frozenset({"finance.stock-research"})),
        understood=_understood(
            needs_external=True,
            instruments=["600519"],
            action=ActionSpec(tool="stock-research", parameters={"symbol": "600519"}),
        ),
    )
    assert action.reason_code == "FINANCE_HANDOFF"


@pytest.mark.asyncio
async def test_action_ignored_when_not_in_allowlist() -> None:
    selector = _selector()
    action = await selector.select(
        _event("600519今天怎么样", enabled_skills=frozenset()),
        understood=_understood(
            needs_external=True,
            instruments=["600519"],
            action=ActionSpec(tool="stock-research", parameters={"symbol": "600519"}),
        ),
    )
    assert action.action_type == CognitiveActionType.RESPOND
    assert action.reason_code == "RESPOND"


@pytest.mark.asyncio
async def test_unset_skills_cannot_call_tools() -> None:
    selector = _selector()
    action = await selector.select(
        _event("600519今天怎么样"),
        understood=_understood(
            needs_external=True,
            instruments=["600519"],
            action=ActionSpec(tool="stock-research", parameters={"symbol": "600519"}),
        ),
    )
    assert action.reason_code == "RESPOND"


@pytest.mark.asyncio
async def test_handlers_route_by_domain_and_wakeup_task_domain() -> None:
    catalog = SkillCatalog(
        (
            SkillToolSpec(skill_id="stock-research", domain="finance"),
            SkillToolSpec(skill_id="forecast", domain="weather"),
        )
    )
    selector = GoalActionSelector(
        handlers={"finance": _Finance(), "weather": _Weather()},
        catalog=catalog,
        respond=_Respond(),
    )
    chosen = await selector.select(
        _event("明天天气", enabled_skills=frozenset({"weather.forecast"})),
        understood=_understood(action=ActionSpec(tool="forecast", parameters={"city": "beijing"})),
    )
    assert chosen.reason_code == "WEATHER_HANDOFF"

    wakeup = await selector.select(
        InputEvent(
            event_id="w1",
            event_type=InputEventType.SCHEDULED_WAKEUP,
            user_id="u1",
            session_id="s1",
            message="wake",
            task_id="t-weather",
            task_domain="weather",
        )
    )
    assert wakeup.reason_code == "WEATHER_HANDOFF"
