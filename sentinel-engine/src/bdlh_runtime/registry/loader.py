"""启动加载 + fail-fast 校验（最终八表目录）。

校验失败抛 ``ConfigurationError``，进程退出；禁止任何代码兜底目录。
资格上限来自 Settings，不在快照内。
"""

from __future__ import annotations

from bdlh_runtime.runtime.errors import ConfigurationError

from .defaults import DEFAULT_RUNTIME_ALLOWED_OPERATIONS
from .models import RegistrySnapshot
from .store import RegistryStore


def load_and_validate(
    store: RegistryStore,
    *,
    runtime_allowed_operations: frozenset[str] | None = None,
) -> RegistrySnapshot:
    """加载目录行并执行全部启动校验；任一失败即拒绝启动。"""
    snapshot = store.load()
    allowed = frozenset(runtime_allowed_operations or DEFAULT_RUNTIME_ALLOWED_OPERATIONS)
    _validate_capabilities(snapshot)
    _validate_skills(snapshot, runtime_allowed=allowed)
    return snapshot


def _validate_capabilities(snapshot: RegistrySnapshot) -> None:
    if not snapshot.capabilities:
        raise ConfigurationError("registry: zero capability rows; refusing to start without catalog")
    known = {cap.name for cap in snapshot.capabilities}
    for cap in snapshot.capabilities:
        if not cap.operations:
            raise ConfigurationError(f"registry: capability {cap.name} has no operation")
        if not cap.toolsets:
            raise ConfigurationError(f"registry: capability {cap.name} has no toolset")
        missing = cap.depends_on - known
        if missing:
            raise ConfigurationError(f"registry: capability {cap.name} depends_on unknown capability {sorted(missing)}")
        unknown_ops = cap.operations - {op.code for op in snapshot.operations}
        if unknown_ops:
            raise ConfigurationError(
                f"registry: capability {cap.name} references unknown operations {sorted(unknown_ops)}"
            )
        if not cap.read_only and cap.enabled:
            raise ConfigurationError(f"registry: capability {cap.name} is writable and enabled")


def _validate_skills(snapshot: RegistrySnapshot, *, runtime_allowed: frozenset[str]) -> None:
    known_caps = {cap.name for cap in snapshot.capabilities}
    known_ops = {op.code for op in snapshot.operations}
    for skill in snapshot.skills:
        missing_caps = {name for name, _ in skill.capabilities} - known_caps
        if missing_caps:
            raise ConfigurationError(
                f"registry: skill {skill.skill_id} references unknown capabilities {sorted(missing_caps)}"
            )
        missing_ops = {code for code, _ in skill.operations} - known_ops
        if missing_ops:
            raise ConfigurationError(
                f"registry: skill {skill.skill_id} references unknown operations {sorted(missing_ops)}"
            )
        if skill.enabled:
            required_ops = {code for code, required in skill.operations if required}
            outside = required_ops - set(runtime_allowed)
            if outside:
                raise ConfigurationError(
                    f"registry: enabled skill {skill.skill_id} required operations "
                    f"outside RUNTIME_ALLOWED_OPERATIONS: {sorted(outside)}"
                )
