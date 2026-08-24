"""按 Understand 的工具调用决策调度行动。

这是普通对话 Agent：LLM 通过 ``action`` 输出 Function Calling 风格的
工具调用指令（``{"tool": "...", "parameters": {...}}``），内核 dispatch 到
对应域 handler。内核不把用户话归因到某个领域。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from bdlh_runtime.cognitive.contracts import (
    RESPOND_UNAVAILABLE_REASON,
    CognitiveAction,
    CognitiveActionType,
    InputEvent,
    InputEventType,
)
from bdlh_runtime.cognitive.goal_schema import UnderstandOutput
from bdlh_runtime.cognitive.plugin_gates import SkillCatalog


class DomainHandoffSelector(Protocol):
    async def select(
        self,
        event: InputEvent,
        *,
        understood: UnderstandOutput | None = None,
    ) -> CognitiveAction: ...


class DirectResponder(Protocol):
    def answer(self, message: str) -> str: ...


class GoalActionSelector:
    """有工具调用决策 → 按 Skill 所属域交给 handler；否则 Agent 直接回答。"""

    def __init__(
        self,
        *,
        handlers: Mapping[str, DomainHandoffSelector],
        catalog: SkillCatalog,
        respond: DirectResponder | None = None,
    ) -> None:
        if not handlers:
            raise ValueError("GoalActionSelector 需要至少一个域 handler")
        self._handlers = dict(handlers)
        self._catalog = catalog
        self._respond = respond

    async def select(
        self,
        event: InputEvent,
        *,
        understood: UnderstandOutput | None = None,
    ) -> CognitiveAction:
        if event.event_type == InputEventType.SCHEDULED_WAKEUP:
            return await self._handler_for(event.task_domain).select(event, understood=understood)

        if understood is None:
            raise ValueError("GoalActionSelector 需要 UnderstandOutput（含 action）")

        chosen = understood.action.tool if understood.action else None
        # 白名单校验：action.tool 必须在本轮 enabled_skills 内（支持 {domain}.{skill} 或 {skill} 形式）
        if chosen:
            if not event.enabled_skills:
                chosen = None
            else:
                allowed = set()
                for item in event.enabled_skills:
                    allowed.add(item)
                    allowed.add(item.split(".", 1)[-1])
                if chosen not in allowed:
                    chosen = None
        domain = self._catalog.domain_for(chosen) if chosen else None
        if chosen and domain is not None and domain in self._handlers:
            return await self._handlers[domain].select(event, understood=understood)

        return self._respond_action(event)

    def _handler_for(self, domain: str | None) -> DomainHandoffSelector:
        if domain and domain in self._handlers:
            return self._handlers[domain]
        raise ValueError(f"没有为任务域 {domain!r} 注册 handler")

    def _respond_action(self, event: InputEvent) -> CognitiveAction:
        if self._respond is None:
            return CognitiveAction(
                action_type=CognitiveActionType.RESPOND,
                reason_code="RESPOND_UNAVAILABLE",
                reason=RESPOND_UNAVAILABLE_REASON,
            )
        return CognitiveAction(
            action_type=CognitiveActionType.RESPOND,
            reason_code="RESPOND",
            reason=self._respond.answer(event.message),
        )
