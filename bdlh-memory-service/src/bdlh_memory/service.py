from __future__ import annotations

from .domain import MemoryCandidate, MemoryRecord, SearchRequest
from .mem0_gateway import Mem0Gateway
from .persistence import InboxRepository


class MemoryApplication:
    def __init__(self, gateway: Mem0Gateway, inbox: InboxRepository) -> None:
        self._gateway = gateway
        self._inbox = inbox

    async def search(self, request: SearchRequest) -> list[MemoryRecord]:
        try:
            return await self._gateway.search(request.user_id, request.query, request.top_k)
        except Exception:
            return []

    async def consume(self, candidate: MemoryCandidate) -> bool:
        if not candidate.policy_allowed() or not self._inbox.claim(candidate.event_id):
            return False
        try:
            await self._gateway.add(candidate.authenticated_user_id, candidate.content, candidate.metadata)
            self._inbox.complete(candidate.event_id, "mem0 add complete")
        except Exception as exc:
            self._inbox.fail(candidate.event_id, type(exc).__name__)
            raise
        return True

    async def get(self, memory_id: str) -> dict | None:
        return await self._gateway.get(memory_id)

    async def delete(self, memory_id: str) -> None:
        await self._gateway.delete(memory_id)

    async def delete_user(self, user_id: str) -> None:
        await self._gateway.delete_user(user_id)
        self._inbox.audit_deletion(user_id, "mem0 and vector data deletion requested")
