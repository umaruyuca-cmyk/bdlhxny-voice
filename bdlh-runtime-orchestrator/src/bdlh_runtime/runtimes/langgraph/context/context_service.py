"""ADR-015 Context Service：唯一的 Mem0 读取与上下文组装边界。"""

from __future__ import annotations

from typing import Any

from .context_builder import BuiltContext, ContextBuilder


class ContextService:
    """只读地取 L3 语义记忆并委托 ContextBuilder 按预算拼装。"""

    is_context_service = True

    def __init__(self, *, builder: ContextBuilder, memory_store: Any | None = None) -> None:
        self._builder = builder
        self._memory_store = memory_store

    async def build(
        self,
        *,
        user_id: str | None,
        conversation: list[dict[str, Any]],
        round_data: list[dict[str, Any]] | None,
        user_input: dict[str, Any],
        purpose: str = "answer",
        budget: str | int = "default",
    ) -> BuiltContext:
        profile: dict[str, Any] | None = None
        recalled: list[dict[str, Any]] = []
        degraded = False
        if self._memory_store is not None and user_id:
            try:
                # L4 profile is assembled by Java User Data API, never by L3 semantic memory.
                profile = None
                query = str(user_input.get("message", ""))
                if query and purpose != "confirm_route":
                    records = await self._memory_store.search(query, user_id, limit=5)
                    recalled = [
                        {"content": item.content, "score": item.score, "metadata": item.metadata}
                        for item in records
                    ]
            except Exception:
                degraded = True
        context = self._builder.build(
            user_profile=profile,
            conversation=conversation,
            recalled_memories=recalled,
            round_data=round_data,
            user_input=user_input,
            purpose=purpose,
            budget=budget,
        )
        if degraded:
            context.dropped.append("semantic_recalls:degraded")
        return context
