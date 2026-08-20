"""L3-only remote Memory Service adapter; failures degrade to empty recall."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from bdlh_runtime.runtime.remote_runtime_data import RuntimeDataClient

from .base import MemoryRecord

logger = logging.getLogger(__name__)


class RemoteMemoryStore:
    def __init__(self, *, base_url: str, internal_token: str, java_client: RuntimeDataClient) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"X-Internal-Token": internal_token}
        self._java_client = java_client

    async def search(self, query: str, user_id: str, *, limit: int = 5) -> list[MemoryRecord]:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.post(
                    f"{self._base_url}/internal/v1/memories/search",
                    headers={**self._headers, "X-Authenticated-User-Id": user_id},
                    json={"user_id": user_id, "query": query[:2000], "top_k": min(max(limit, 1), 10)},
                )
            response.raise_for_status()
            return [
                MemoryRecord(
                    content=str(item["content"]),
                    score=float(item.get("score", 0.0)),
                    metadata=dict(item.get("metadata") or {}),
                )
                for item in response.json()
            ]
        except Exception as exc:
            logger.warning("Memory Service search degraded: %s", type(exc).__name__)
            return []

    async def add(self, content: str, user_id: str, *, metadata: dict[str, Any] | None = None) -> None:
        metadata = metadata or {}
        if metadata.get("knowledge_type") != "confirmed":
            return
        candidate_id = str(uuid4())
        try:
            await asyncio.to_thread(
                self._java_client.call,
                "POST",
                "/internal/v1/memory-candidates",
                user_id,
                payload={
                    "candidateId": candidate_id,
                    "content": content[:1200],
                    "metadata": metadata,
                    "traceId": f"memory-candidate:{candidate_id}",
                    "correlationId": str(metadata.get("run_id") or candidate_id),
                },
            )
        except Exception as exc:
            logger.warning("Memory candidate enqueue degraded: %s", type(exc).__name__)
