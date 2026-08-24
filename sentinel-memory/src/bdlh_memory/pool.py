"""Memory Service PostgreSQL connection-pool lifecycle."""

from __future__ import annotations

from typing import Any


def build_pool(dsn: str, *, max_size: int = 4) -> Any:
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        conninfo=dsn,
        min_size=1,
        max_size=max_size,
        timeout=3,
        max_idle=60,
        open=False,
    )
    pool.open(wait=True)
    return pool
