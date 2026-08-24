"""Run Registry 工厂与内存实现回归。"""

from __future__ import annotations

import pytest

from bdlh_runtime.infra.errors import ConfigurationError
from bdlh_runtime.infra.run_registry import (
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


def test_create_run_registry_always_refuses() -> None:
    with pytest.raises(ConfigurationError, match="Java Data Plane"):
        create_run_registry()
    with pytest.raises(ConfigurationError, match="Java Data Plane"):
        create_run_registry(environment="test")
    with pytest.raises(ConfigurationError, match="Java Data Plane"):
        create_run_registry(environment="production")
