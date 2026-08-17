"""Checkpointer 工厂：DSN 优先走 PostgreSQL。"""

from __future__ import annotations

import pytest

from bdlh_runtime.config import Settings
from bdlh_runtime.runtime.checkpointers import create_checkpointer
from bdlh_runtime.runtime.errors import ConfigurationError


def test_memory_backend_without_dsn_stays_in_memory() -> None:
    checkpointer = create_checkpointer(
        Settings(environment="development", checkpointer_backend="memory")
    )
    assert checkpointer is not None


def test_memory_backend_with_dsn_auto_selects_postgres() -> None:
    with pytest.raises(ConfigurationError, match="postgres Checkpointer|PostgreSQL Checkpointer"):
        create_checkpointer(
            Settings(
                environment="development",
                checkpointer_backend="memory",
                postgres_dsn="postgresql://invalid:invalid@127.0.0.1:1/none",
            )
        )
