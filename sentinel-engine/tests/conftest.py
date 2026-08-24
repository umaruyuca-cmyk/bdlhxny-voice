"""测试共享 fixture：注册表快照（与种子迁移行语义一致）。

生产目录真源是 Java Data Plane（根目录 `db/postgresql/seed/registry.sql`）；
无 PG 的单测统一注入该快照（重写 §6.2：单测用 InMemoryRegistryStore
插入与种子相同的行，禁止内存默认兜底进入生产路径）。
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from bdlh_runtime.registry import load_and_validate

from .registry.seeded_store import build_seeded_store


@pytest.fixture(scope="session")
def registry_snapshot():
    """与种子行一致的 RegistrySnapshot（session 级共享）。"""
    return load_and_validate(build_seeded_store())


@pytest.fixture(scope="session")
def seeded_store():
    """未校验的内存仓储（需要自定义行时用 copy 修改）。"""
    return build_seeded_store()
