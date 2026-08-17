"""把语义路由命中映射为 CognitiveAction；未命中则交给后续选择器。

高置信闲聊/知识/禁止在内核结束；复合任务不在这里选 Skill。
"""

from __future__ import annotations

from typing import Protocol

from bdlh_runtime.cognitive.contracts import (
    CognitiveAction,
    CognitiveActionType,
    InputEvent,
)

from .contracts import RouteChoice, RouteDisposition
from .router import SemanticRouter


class FallbackSelector(Protocol):
    async def select(self, event: InputEvent) -> CognitiveAction: ...


class KnowledgeResponder(Protocol):
    def answer(self, message: str) -> str: ...


class SemanticRouteSelector:
    """Cognitive 入口的快路径过滤器，本身不是领域选择器。"""

    def __init__(
        self,
        router: SemanticRouter,
        *,
        fallback: FallbackSelector,
        knowledge_responder: KnowledgeResponder | None = None,
    ) -> None:
        self._router = router
        self._fallback = fallback
        self._knowledge_responder = knowledge_responder

    async def select(self, event: InputEvent) -> CognitiveAction:
        # 1. 低于阈值或空命中：进入 Understand / 领域选择器，不假装已分类。
        choice = self._router.route(event.message)
        if choice is None:
            return await self._fallback.select(event)
        if choice.disposition == RouteDisposition.BLOCK:
            return CognitiveAction(
                action_type=CognitiveActionType.RESPOND,
                reason_code="SEMANTIC_FORBIDDEN",
                reason=choice.response or "该请求不被允许。",
            )
        # 2. 知识问答优先用无工具回答器；没有回答器时不丢给错误 Skill，而是回退。
        if choice.name == "knowledge":
            if self._knowledge_responder is None:
                return await self._fallback.select(event)
            return CognitiveAction(
                action_type=CognitiveActionType.RESPOND,
                reason_code="SEMANTIC_KNOWLEDGE",
                reason=self._knowledge_responder.answer(event.message),
            )
        return CognitiveAction(
            action_type=CognitiveActionType.RESPOND,
            reason_code=f"SEMANTIC_{choice.name.upper()}",
            reason=choice.response or _default_respond_text(choice),
        )


def _default_respond_text(choice: RouteChoice) -> str:
    return f"已按 {choice.name} 快路径处理。"
