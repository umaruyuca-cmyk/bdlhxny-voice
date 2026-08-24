"""registry 启动校验测试：空库/校验失败拒绝启动。"""

from __future__ import annotations

import pytest

from bdlh_runtime.registry import InMemoryRegistryStore, load_and_validate
from bdlh_runtime.runtime.errors import ConfigurationError

from .seeded_store import build_seeded_store


def test_seeded_store_passes_validation() -> None:
    """与种子一致的目录通过全部启动校验。"""
    snapshot = load_and_validate(build_seeded_store())
    assert len(snapshot.capabilities) == 16
    assert any(skill.skill_id == "stock-research" and skill.enabled for skill in snapshot.skills)


def test_empty_catalog_refuses_to_start() -> None:
    """零 capability 行拒绝启动，禁止代码兜底。"""
    with pytest.raises(ConfigurationError, match="zero capability"):
        load_and_validate(InMemoryRegistryStore())


def test_missing_dependency_refuses_to_start() -> None:
    store = build_seeded_store()
    store.capabilities = [cap for cap in store.capabilities if cap.name != "market.resolve_instrument"]
    with pytest.raises(ConfigurationError, match="depends_on unknown"):
        load_and_validate(store)


def test_enabled_skill_outside_runtime_allowlist_refuses_to_start() -> None:
    with pytest.raises(ConfigurationError, match="RUNTIME_ALLOWED_OPERATIONS"):
        load_and_validate(
            build_seeded_store(),
            runtime_allowed_operations=frozenset({"RUN_ANALYSIS"}),
        )


def test_enabled_writable_capability_refuses_to_start() -> None:
    from dataclasses import replace

    store = build_seeded_store()
    store.capabilities = [
        replace(cap, read_only=False) if cap.name == "market.get_news" else cap for cap in store.capabilities
    ]
    with pytest.raises(ConfigurationError, match="writable"):
        load_and_validate(store)
