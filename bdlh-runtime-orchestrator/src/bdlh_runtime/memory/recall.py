"""L3 语义召回结果（ADR-017：失败空结果 + degraded，不污染主链路）。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .base import MemoryRecord

logger = logging.getLogger("bdlh_runtime.memory.recall")


@dataclass
class MemoryRecallResult:
    records: list[MemoryRecord] = field(default_factory=list)
    degraded: bool = False
    limitation: str | None = None


async def recall_semantic_memory(
    store: Any,
    *,
    user_id: str,
    query: str,
    limit: int = 5,
) -> MemoryRecallResult:
    """入口召回；失败返回空列表并标记 degraded，禁止假造成功。"""
    if store is None:
        return MemoryRecallResult(degraded=False, limitation=None)
    try:
        if hasattr(store, "search_with_status"):
            records, degraded = await store.search_with_status(query, user_id, limit=limit)
            return MemoryRecallResult(
                records=list(records or []),
                degraded=bool(degraded),
                limitation="semantic_memory_degraded" if degraded else None,
            )
        records = await store.search(query, user_id, limit=limit)
        degraded = bool(getattr(store, "last_search_degraded", False))
        return MemoryRecallResult(
            records=list(records or []),
            degraded=degraded,
            limitation="semantic_memory_degraded" if degraded else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory_recall_degraded err=%s", type(exc).__name__)
        return MemoryRecallResult(
            records=[],
            degraded=True,
            limitation="semantic_memory_degraded",
        )
