"""可选场景包注册表。

平台默认领域中立。场景包(如 finance)必须显式启用才注入工具集映射、
危险动作词表、出口护栏与描述覆盖。未启用时不影响任何默认行为。

启用方式:
- 环境变量 ``SCENARIO_PACKS=finance``(逗号分隔多个包);
- 或代码调用 ``enable_scenario_pack("finance")``。
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

_PACK_LOADERS: dict[str, Callable[[], None]] = {}
_ENABLED: set[str] = set()
_BOOTSTRAPPED = False


def register_pack(name: str, loader: Callable[[], None]) -> None:
    """登记场景包加载器(导入包模块时调用)。"""
    _PACK_LOADERS[name] = loader


def enabled_packs() -> frozenset[str]:
    _ensure_env_bootstrap()
    return frozenset(_ENABLED)


def is_pack_enabled(name: str) -> bool:
    return name in enabled_packs()


def enable_scenario_pack(name: str) -> None:
    """显式启用场景包;重复调用幂等。"""
    _ensure_env_bootstrap()
    if name in _ENABLED:
        return
    loader = _PACK_LOADERS.get(name)
    if loader is None:
        # 延迟导入内置包
        _try_import_builtin(name)
        loader = _PACK_LOADERS.get(name)
    if loader is None:
        raise ValueError(f"未知场景包:{name!r};已登记:{sorted(_PACK_LOADERS)}")
    loader()
    _ENABLED.add(name)


def disable_all_scenario_packs() -> None:
    """测试用:清空已启用集合并重置可注入钩子(不卸载已 import 模块)。"""
    global _BOOTSTRAPPED
    _ENABLED.clear()
    _BOOTSTRAPPED = True
    from bdlh_runtime.scenarios.dangerous_actions import clear_profiles

    clear_profiles()
    from bdlh_runtime.engine import loader as tool_loader

    tool_loader.reset_scene_toolsets_to_core()
    from bdlh_runtime.engine.output_guardrail import reset_default_output_checks

    reset_default_output_checks()


def _try_import_builtin(name: str) -> None:
    if name == "finance":
        from bdlh_runtime.scenarios import finance as _finance  # noqa: F401


def _ensure_env_bootstrap() -> None:
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    _BOOTSTRAPPED = True
    raw = (os.getenv("SCENARIO_PACKS") or "").strip()
    if not raw:
        return
    for part in raw.split(","):
        name = part.strip()
        if name:
            enable_scenario_pack(name)


def apply_description_overlays(name: str, fallback: str) -> str:
    """场景包可为工具名覆盖双目的描述;未命中返回 fallback。"""
    _ensure_env_bootstrap()
    for pack_name in _ENABLED:
        overlays = _PACK_DESCRIPTION_OVERLAYS.get(pack_name) or {}
        if name in overlays:
            return overlays[name]
    return fallback


_PACK_DESCRIPTION_OVERLAYS: dict[str, dict[str, str]] = {}


def register_description_overlays(pack: str, overlays: dict[str, str]) -> None:
    _PACK_DESCRIPTION_OVERLAYS[pack] = dict(overlays)


def pack_status() -> dict[str, Any]:
    return {
        "registered": sorted(_PACK_LOADERS),
        "enabled": sorted(_ENABLED),
        "env": (os.getenv("SCENARIO_PACKS") or "").strip(),
    }
