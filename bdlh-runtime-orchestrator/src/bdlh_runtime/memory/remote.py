"""L3-only remote Memory Service adapter（G7）。

读：Memory Service HTTP；失败 → 空列表 + degraded（不得静默假装「召回成功」）。
写：仅经 Java ``/internal/v1/memory-candidates`` 进 Outbox；失败 → degraded，不直连 Mem0。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from bdlh_runtime.runtime.remote_runtime_data import RuntimeDataClient

from .base import MemoryRecord
from .writer import MemoryWriteResult, MemoryWriter

logger = logging.getLogger(__name__)


class RemoteMemoryStore:
    def __init__(self, *, base_url: str, internal_token: str, java_client: RuntimeDataClient) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"X-Internal-Token": internal_token}
        self._java_client = java_client
        self.last_search_degraded: bool = False
        self._writer = MemoryWriter(self)

    async def search(self, query: str, user_id: str, *, limit: int = 5) -> list[MemoryRecord]:
        records, _degraded = await self.search_with_status(query, user_id, limit=limit)
        return records

    async def search_with_status(
        self,
        query: str,
        user_id: str,
        *,
        limit: int = 5,
    ) -> tuple[list[MemoryRecord], bool]:
        self.last_search_degraded = False
        try:
            import httpx

            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.post(
                    f"{self._base_url}/internal/v1/memories/search",
                    headers={**self._headers, "X-Authenticated-User-Id": user_id},
                    json={"user_id": user_id, "query": query[:2000], "top_k": min(max(limit, 1), 10)},
                )
            response.raise_for_status()
            payload = response.json()
            items = payload if isinstance(payload, list) else payload.get("items", [])
            records = [
                MemoryRecord(
                    content=str(item["content"]),
                    score=float(item.get("score", 0.0)),
                    metadata={**dict(item.get("metadata") or {}), "layer": "L3"},
                    layer="L3",
                )
                for item in items
                if item.get("content")
            ]
            return records, False
        except Exception as exc:
            self.last_search_degraded = True
            logger.warning("Memory Service search degraded: %s", type(exc).__name__)
            return [], True

    async def add(self, content: str, user_id: str, *, metadata: dict[str, Any] | None = None) -> MemoryWriteResult:
        """投递候选到 Java Outbox；过滤失败不 enqueue，网络失败标记 degraded。"""
        filtered = self._writer.filter_candidate(content, metadata=metadata)
        if filtered is None:
            return MemoryWriteResult(
                attempted=False,
                enqueued=False,
                skipped_reason="filtered_or_unconfirmed",
            )
        text, meta = filtered
        candidate_id = str(uuid4())
        try:
            await asyncio.to_thread(
                self._java_client.call,
                "POST",
                "/internal/v1/memory-candidates",
                user_id,
                payload={
                    "candidateId": candidate_id,
                    "content": text[:1200],
                    "metadata": meta,
                    "traceId": f"memory-candidate:{candidate_id}",
                    "correlationId": str(meta.get("run_id") or candidate_id),
                },
            )
            return MemoryWriteResult(attempted=True, enqueued=True)
        except Exception as exc:
            logger.warning("Memory candidate enqueue degraded: %s", type(exc).__name__)
            return MemoryWriteResult(
                attempted=True,
                enqueued=False,
                skipped_reason=type(exc).__name__,
                degraded=True,
            )
