"""分析历史端口。

运行时唯一持久化实现位于 Java Data Plane。这里保留的内存实现只供隔离单元
测试使用，禁止 Python 服务直接连接 PostgreSQL 或执行运行时 DDL。
"""

from __future__ import annotations

from typing import Protocol

from bdlh_runtime.contracts.history import AnalysisHistoryRecord
from bdlh_runtime.runtime.errors import ConfigurationError


class AnalysisHistoryStore(Protocol):
    def save(self, record: AnalysisHistoryRecord) -> None: ...

    def get(self, history_id: str) -> AnalysisHistoryRecord | None: ...

    def list_by_thread(self, thread_id: str, user_id: str | None) -> list[AnalysisHistoryRecord]: ...


class InMemoryAnalysisHistoryStore:
    """测试专用实现。"""

    def __init__(self) -> None:
        self._records: dict[str, AnalysisHistoryRecord] = {}
        self._by_thread: dict[str, list[str]] = {}

    def save(self, record: AnalysisHistoryRecord) -> None:
        self._records[record.history_id] = record
        ids = self._by_thread.setdefault(record.thread_id, [])
        if record.history_id not in ids:
            ids.append(record.history_id)

    def get(self, history_id: str) -> AnalysisHistoryRecord | None:
        return self._records.get(history_id)

    def list_by_thread(self, thread_id: str, user_id: str | None) -> list[AnalysisHistoryRecord]:
        if user_id is None:
            return []
        return [
            self._records[history_id]
            for history_id in self._by_thread.get(thread_id, [])
            if history_id in self._records and self._records[history_id].authenticated_user_id == user_id
        ]


def create_history_store(*, environment: str = "test") -> AnalysisHistoryStore:
    """创建测试用内存历史存储；运行时数据必须经 Java Data Plane。"""

    if environment != "test":
        raise ConfigurationError("Python 内存 History Store 仅允许测试环境")
    return InMemoryAnalysisHistoryStore()
