"""Run Registry 工厂与内存实现回归。"""

from __future__ import annotations

import pytest

from bdlh_runtime.runtime.errors import ConfigurationError
from bdlh_runtime.runtime.run_registry import (
    InMemoryRunRegistry,
    RunLocation,
    create_run_registry,
)


def test_in_memory_registry_round_trip() -> None:
    registry = InMemoryRunRegistry()
    location = RunLocation(
        run_id="run-1",
        thread_id="thread-1",
        user_id="user-1",
        checkpoint_id="cp-1",
        runtime_path="cognitive",
    )
    registry.register(location)
    assert registry.get("run-1") == location
    assert registry.get("run-1", "user-1") == location
    assert registry.get("run-1", "other-user") is None
    assert registry.get("missing") is None


def test_create_run_registry_returns_in_memory_without_dsn() -> None:
    registry = create_run_registry(environment="development")
    assert isinstance(registry, InMemoryRunRegistry)


def test_create_run_registry_requires_dsn_in_production() -> None:
    with pytest.raises(ConfigurationError, match="POSTGRES_DSN"):
        create_run_registry(environment="production", postgres_dsn=None)
