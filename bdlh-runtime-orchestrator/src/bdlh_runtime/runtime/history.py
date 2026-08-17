"""分析历史存储（v2.1 §9.3）。

开发/测试默认内存；生产使用 PostgreSQL 持久化。
查询权限：仅本人（按 authenticated_user_id 隔离，v2.1 P0-6 安全边界）。
"""

from __future__ import annotations

import json
import logging
from typing import Protocol

from bdlh_runtime.contracts.history import AnalysisHistoryRecord
from bdlh_runtime.runtime.errors import ConfigurationError

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
        ids = self._by_thread.setdefault(record.thread_id, [])
        if record.history_id not in ids:
            ids.append(record.history_id)

    def get(self, history_id: str) -> AnalysisHistoryRecord | None:
        return self._records.get(history_id)

    def list_by_thread(self, thread_id: str, user_id: str | None) -> list[AnalysisHistoryRecord]:
        """按 thread 查询历史；权限隔离：仅本人可查（user_id 不匹配返回空）。"""
        ids = self._by_thread.get(thread_id, [])
        records = [self._records[hid] for hid in ids if hid in self._records]
        if user_id is None:
            return []
        return [r for r in records if r.authenticated_user_id == user_id]


class PostgresAnalysisHistoryStore:
    """生产 Analysis History；审计与历史查询持久化到 PostgreSQL。"""

    def __init__(self, dsn: str) -> None:
        try:
            import psycopg  # noqa: F401
        except ImportError as exc:
            raise ConfigurationError(
                "PostgreSQL Analysis History 需要安装 psycopg[binary]"
            ) from exc
        self._dsn = dsn
        self._setup()

    def _connect(self):
        import psycopg

        return psycopg.connect(self._dsn)

    def _setup(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bdlh_runtime_analysis_history (
                    history_id VARCHAR(64) PRIMARY KEY,
                    thread_id VARCHAR(255) NOT NULL,
                    run_id VARCHAR(64) NOT NULL,
                    authenticated_user_id VARCHAR(64),
                    status VARCHAR(32) NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bdlh_runtime_analysis_history_thread_user
                ON bdlh_runtime_analysis_history(
                    thread_id, authenticated_user_id, created_at
                )
                """
            )

    @staticmethod
    def _decode(payload: object) -> AnalysisHistoryRecord:
        if isinstance(payload, str):
            payload = json.loads(payload)
        return AnalysisHistoryRecord.model_validate(payload)

    def save(self, record: AnalysisHistoryRecord) -> None:
        payload = record.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO bdlh_runtime_analysis_history(
                    history_id, thread_id, run_id, authenticated_user_id,
                    status, payload, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s::jsonb,
                    COALESCE(%s::timestamptz, CURRENT_TIMESTAMP)
                )
                ON CONFLICT (history_id) DO UPDATE SET
                    thread_id = EXCLUDED.thread_id,
                    run_id = EXCLUDED.run_id,
                    authenticated_user_id = EXCLUDED.authenticated_user_id,
                    status = EXCLUDED.status,
                    payload = EXCLUDED.payload
                """,
                (
                    record.history_id,
                    record.thread_id,
                    record.run_id,
                    record.authenticated_user_id,
                    record.status,
                    json.dumps(payload, ensure_ascii=False),
                    record.created_at,
                ),
            )

    def get(self, history_id: str) -> AnalysisHistoryRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM bdlh_runtime_analysis_history WHERE history_id = %s",
                (history_id,),
            ).fetchone()
        return self._decode(row[0]) if row else None

    def list_by_thread(
        self, thread_id: str, user_id: str | None
    ) -> list[AnalysisHistoryRecord]:
        if user_id is None:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM bdlh_runtime_analysis_history
                WHERE thread_id = %s AND authenticated_user_id = %s
                ORDER BY created_at ASC, history_id ASC
                """,
                (thread_id, user_id),
            ).fetchall()
        return [self._decode(row[0]) for row in rows]


def create_history_store(
    *,
    environment: str = "development",
    postgres_dsn: str | None = None,
) -> AnalysisHistoryStore:
    """创建历史存储。

    有 ``POSTGRES_DSN`` 时（任意环境，含云上联调）一律使用 PostgreSQL；
    仅本地单测未配置 DSN 时退回内存。生产缺少 DSN 时 fail-closed。
    """

    if postgres_dsn:
        return PostgresAnalysisHistoryStore(postgres_dsn)
    if environment == "production":
        raise ConfigurationError("生产 Analysis History 需要 POSTGRES_DSN")
    return InMemoryAnalysisHistoryStore()
