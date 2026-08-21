"""把语义路由命中映射为 CognitiveAction；未命中返回 None。

高置信闲聊/知识/禁止在内核结束；复合任务不在这里选 Skill 或领域。
启用了 finance Skill 的知识题交回上层，由 GoalAction → 金融插件处理。
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from bdlh_runtime.cognitive.contracts import (
    CognitiveAction,
    CognitiveActionType,
    InputEvent,
)
from bdlh_runtime.cognitive.plugin_gates import finance_skill_enabled

from .contracts import RouteChoice, RouteDisposition
from .router import SemanticRouter


class KnowledgeResponder(Protocol):
    def answer(self, message: str) -> str: ...


class SemanticRouteSelector:
    """内核快路径：闲聊 / 知识 / 禁止。未命中返回 None，由 GoalActionSelector 接管。"""

    def __init__(
        self,
        router: SemanticRouter,
        *,
        knowledge_responder: KnowledgeResponder | None = None,
    ) -> None:
        self._router = router
        self._knowledge_responder = knowledge_responder

    async def try_fastpath(self, event: InputEvent) -> CognitiveAction | None:
        # 模型编码是同步阻塞 HTTP 调用，放入线程避免卡住事件循环。
        choice = await asyncio.to_thread(self._router.route, event.message)
        if choice is None:
            return None
        if choice.disposition == RouteDisposition.BLOCK:
            return CognitiveAction(
                action_type=CognitiveActionType.RESPOND,
                reason_code="SEMANTIC_FORBIDDEN",
                reason=choice.response or "该请求不被允许。",
            )
        if choice.name == "knowledge":
            # Skill 已开：知识分析归金融插件；未开：内核直接答
            if event.enabled_skills is not None and finance_skill_enabled(event.enabled_skills):
                return None
            if self._knowledge_responder is None:
                return None
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
