"""测试专用能力目录构建（与种子行一致）。

仅供 tests 使用：生产路径的目录真源是 Postgres（loader fail-fast），
禁止代码默认清单兜底；本 helper 是「测试注入与种子相同的行」的便捷形式
（重写 §6.2 允许的 InMemoryRegistryStore 用法）。
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bdlh_runtime.registry import load_and_validate
from bdlh_runtime.tools.capabilities import CapabilityRegistry, load_capability_registry

from .registry.seeded_store import build_seeded_store

_SNAPSHOT = None
_REGISTRY: CapabilityRegistry | None = None


def seeded_snapshot():
    global _SNAPSHOT
    if _SNAPSHOT is None:
        _SNAPSHOT = load_and_validate(build_seeded_store())
    return _SNAPSHOT


def build_default_capability_registry() -> CapabilityRegistry:
    """测试兼容入口：返回与种子行一致的能力目录（每调用新实例，供注册探针等）。"""
    return load_capability_registry(seeded_snapshot())
