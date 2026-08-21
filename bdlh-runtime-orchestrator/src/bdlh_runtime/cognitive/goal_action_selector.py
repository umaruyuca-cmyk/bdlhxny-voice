"""按 Understand 结果选择行动；金融 Skill 仅在确有金融信号时交接。

产品模型：ChatGPT 式对话 + 可选插件。
``needs_external`` 只表示可能要用外部能力，**不等于**交给金融域。
"""

from __future__ import annotations

from typing import Protocol

from bdlh_runtime.cognitive.contracts import (
    CognitiveAction,
    CognitiveActionType,
    InputEvent,
    InputEventType,
)
from bdlh_runtime.cognitive.goal_schema import UnderstandOutput
from bdlh_runtime.cognitive.plugin_gates import (
    finance_skill_enabled,
    message_suggests_finance_plugin,
)


class DomainHandoffSelector(Protocol):
    async def select(
        self,
        event: InputEvent,
        *,
        understood: UnderstandOutput | None = None,
    ) -> CognitiveAction: ...


class DirectResponder(Protocol):
    def answer(self, message: str) -> str: ...


_MISSING_HINTS: dict[str, str] = {
    "instrument": "请补充你想了解的证券代码、公司名称或简称。",
    "objective": "请再具体说明你想完成什么。",
    "time_range": "请补充关注的时间范围。",
    "理解失败": "暂时无法理解你的问题，请换一种说法或稍后重试。",
}

_FINANCE_MARKET_TOPICS = frozenset({"news", "money_flow", "industry"})


class GoalActionSelector:
    """missing → ASK_USER；有金融信号且 Skill 允许 → 插件交接；其余普通对话。"""

    def __init__(
        self,
        *,
        finance: DomainHandoffSelector,
        respond: DirectResponder | None = None,
    ) -> None:
        self._finance = finance
        self._respond = respond

    async def select(
        self,
        event: InputEvent,
        *,
        understood: UnderstandOutput | None = None,
    ) -> CognitiveAction:
        if event.event_type == InputEventType.SCHEDULED_WAKEUP:
            return await self._finance.select(event, understood=understood)

        if understood is None:
            raise ValueError("GoalActionSelector 需要 UnderstandOutput（快路径未命中后）")

        if understood.missing:
            return CognitiveAction(
                action_type=CognitiveActionType.ASK_USER,
                reason_code="UNDERSTAND_MISSING",
                reason=_missing_prompt(understood.missing),
                related_goal_ids=[goal.goal_id for goal in understood.goals],
            )

        finance_signal = wants_finance_plugin(understood, event.message)
        if finance_signal and _finance_plugin_allowed(event):
            return await self._finance.select(event, understood=understood)

        if finance_signal and not _finance_plugin_allowed(event):
            return self._general_chat(event, reason_code="GENERAL_CHAT_NO_FINANCE")

        return self._general_chat(event, reason_code="GENERAL_CHAT")

    def _general_chat(self, event: InputEvent, *, reason_code: str) -> CognitiveAction:
        if self._respond is None:
            return CognitiveAction(
                action_type=CognitiveActionType.RESPOND,
                reason_code="GENERAL_CHAT_UNAVAILABLE",
                reason="当前对话能力暂不可用，请稍后重试。",
            )
        return CognitiveAction(
            action_type=CognitiveActionType.RESPOND,
            reason_code=reason_code,
            reason=self._respond.answer(event.message),
        )


def wants_finance_plugin(understood: UnderstandOutput, message: str) -> bool:
    """是否出现应交给金融 Skill 插件的信号（与 needs_external 解耦）。"""
    if understood.entities.instruments:
        return True
    for goal in understood.goals:
        if goal.needs_account or goal.needs_profile:
            return True
        if any(topic in _FINANCE_MARKET_TOPICS for topic in goal.requested_topics):
            return True
        if "web_research" in goal.requested_topics and understood.entities.instruments:
            return True
    return message_suggests_finance_plugin(message)


def _finance_plugin_allowed(event: InputEvent) -> bool:
    if event.enabled_skills is None:
        return True
    return finance_skill_enabled(event.enabled_skills)


def _missing_prompt(missing: list[str]) -> str:
    parts = [_MISSING_HINTS.get(item, f"请补充：{item}") for item in missing]
    return " ".join(parts)
