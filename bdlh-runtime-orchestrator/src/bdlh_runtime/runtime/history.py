"""分析历史存储（v2.1 §9.3）。

当前为内存实现（开发/测试）；生产替换为 PG 持久化。
查询权限：仅本人（按 authenticated_user_id 隔离，v2.1 P0-6 安全边界）。
"""

from __future__ import annotations

import logging
from typing import Protocol

from bdlh_runtime.contracts.history import AnalysisHistoryRecord

logger = logging.getLogger("bdlh_runtime.runtime.history")


class AnalysisHistoryStore(Protocol):
    def save(self, record: AnalysisHistoryRecord) -> None: ...
    def get(self, history_id: str) -> AnalysisHistoryRecord | None: ...
    def list_by_thread(self, thread_id: str, user_id: str | None) -> list[AnalysisHistoryRecord]: ...


class InMemoryAnalysisHistoryStore:
    """内存实现（开发/测试）；生产替换为 PG 持久化。"""

    def __init__(self) -> None:
        self._records: dict[str, AnalysisHistoryRecord] = {}
        self._by_thread: dict[str, list[str]] = {}

    def save(self, record: AnalysisHistoryRecord) -> None:
        self._records[record.history_id] = record
        self._by_thread.setdefault(record.thread_id, []).append(record.history_id)

    def get(self, history_id: str) -> AnalysisHistoryRecord | None:
        return self._records.get(history_id)

    def list_by_thread(self, thread_id: str, user_id: str | None) -> list[AnalysisHistoryRecord]:
        """按 thread 查询历史；权限隔离：仅本人可查（user_id 不匹配返回空）。"""
        ids = self._by_thread.get(thread_id, [])
        records = [self._records[hid] for hid in ids if hid in self._records]
        if user_id is None:
            return []
        return [r for r in records if r.authenticated_user_id == user_id]


def create_history_store() -> AnalysisHistoryStore:
    """创建历史存储（当前内存版；生产替换 PG）。"""
    return InMemoryAnalysisHistoryStore()
