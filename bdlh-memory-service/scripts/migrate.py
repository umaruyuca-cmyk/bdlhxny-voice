"""Explicit Memory Service migration runner; never invoked by application startup."""

from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    dsn = os.environ.get("MEMORY_POSTGRES_DSN")
    if not dsn:
        raise SystemExit("MEMORY_POSTGRES_DSN is required")
    import psycopg

    migration = Path(__file__).parents[1] / "db" / "migration" / "V1__memory_inbox_and_deletion_audit.sql"
    with psycopg.connect(dsn) as connection:
        connection.execute(migration.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
