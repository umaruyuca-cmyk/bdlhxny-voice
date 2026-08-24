"""Tests-only memory store stub — not a product path."""

from __future__ import annotations

from typing import Any

from bdlh_runtime.memory.base import MemoryRecord
from bdlh_runtime.memory.writer import MemoryWriteResult


class StubMemoryStore:
    """空 search / 静默 add；隔离测试不依赖 Remote Memory。"""

    async def search(self, query: str, user_id: str, *, limit: int = 5) -> list[MemoryRecord]:
        del query, user_id, limit
        return []

    async def add(self, content: str, user_id: str, *, metadata: dict[str, Any] | None = None) -> MemoryWriteResult:
        del content, user_id, metadata
        return MemoryWriteResult(attempted=False, enqueued=False, skipped_reason="test_stub")
