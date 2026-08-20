"""运行定位注册表。

API 对外使用 ``run_id``，LangGraph Checkpointer 使用 ``thread_id``。当两者
不相同时，恢复和查询必须先通过本注册表定位真实 thread_id，不能假设二者相等。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bdlh_runtime.runtime.errors import ConfigurationError


@dataclass(frozen=True)
class RunLocation:
    """一次运行在 Checkpointer 中的定位信息。"""

    run_id: str
    thread_id: str
    user_id: str | None = None
    checkpoint_id: str | None = None
    runtime_path: str = "legacy_root_graph"


class RunRegistry(Protocol):
    """run_id 到 Checkpointer thread_id 的索引契约。"""

    def register(self, location: RunLocation) -> None:
        """登记一次运行。"""
        ...

    def get(self, run_id: str, user_id: str | None = None) -> RunLocation | None:
        """按 run_id 查询运行位置；提供用户时必须匹配记录所有者。"""
        ...


class InMemoryRunRegistry:
    """开发/测试实现；生产环境替换为持久化索引。"""

    def __init__(self) -> None:
        self._locations: dict[str, RunLocation] = {}

    def register(self, location: RunLocation) -> None:
        self._locations[location.run_id] = location

    def get(self, run_id: str, user_id: str | None = None) -> RunLocation | None:
        location = self._locations.get(run_id)
        if location is None or user_id is None:
            return location
        return location if str(location.user_id) == str(user_id) else None


class PostgresRunRegistry:
    """生产 Run Registry；run_id → thread/checkpoint 定位持久化到 PostgreSQL。"""

    def __init__(self, dsn: str) -> None:
        try:
            import psycopg  # noqa: F401
        except ImportError as exc:
            raise ConfigurationError(
                "PostgreSQL Run Registry 需要安装 psycopg[binary]"
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
                CREATE TABLE IF NOT EXISTS bdlh_runtime_run_registry (
                    run_id VARCHAR(64) PRIMARY KEY,
                    thread_id VARCHAR(255) NOT NULL,
                    user_id VARCHAR(64),
                    checkpoint_id VARCHAR(255),
                    runtime_path VARCHAR(64) NOT NULL DEFAULT 'legacy_root_graph',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bdlh_runtime_run_registry_thread
                ON bdlh_runtime_run_registry(thread_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bdlh_runtime_run_registry_user
                ON bdlh_runtime_run_registry(user_id, updated_at DESC)
                """
            )

    def register(self, location: RunLocation) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO bdlh_runtime_run_registry(
                    run_id, thread_id, user_id, checkpoint_id, runtime_path
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE SET
                    thread_id = EXCLUDED.thread_id,
                    user_id = EXCLUDED.user_id,
                    checkpoint_id = EXCLUDED.checkpoint_id,
                    runtime_path = EXCLUDED.runtime_path,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    location.run_id,
                    location.thread_id,
                    location.user_id,
                    location.checkpoint_id,
                    location.runtime_path,
                ),
            )

    def get(self, run_id: str, user_id: str | None = None) -> RunLocation | None:
        with self._connect() as connection:
            if user_id is None:
                row = connection.execute(
                    """
                    SELECT run_id, thread_id, user_id, checkpoint_id, runtime_path
                    FROM bdlh_runtime_run_registry
                    WHERE run_id = %s
                    """,
                    (run_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT run_id, thread_id, user_id, checkpoint_id, runtime_path
                    FROM bdlh_runtime_run_registry
                    WHERE run_id = %s AND user_id = %s
                    """,
                    (run_id, str(user_id)),
                ).fetchone()
        if row is None:
            return None
        return RunLocation(
            run_id=row[0],
            thread_id=row[1],
            user_id=row[2],
            checkpoint_id=row[3],
            runtime_path=row[4] or "legacy_root_graph",
        )


def create_run_registry(
    *,
    environment: str = "development",
    postgres_dsn: str | None = None,
) -> RunRegistry:
    """创建运行注册表。

    有 ``POSTGRES_DSN`` 时（任意环境，含云上联调）一律使用 PostgreSQL；
    仅本地单测未配置 DSN 时退回内存。生产缺少 DSN 时 fail-closed。
    """

    if postgres_dsn:
        return PostgresRunRegistry(postgres_dsn)
    if environment == "production":
        raise ConfigurationError("生产 Run Registry 需要 POSTGRES_DSN")
    return InMemoryRunRegistry()
