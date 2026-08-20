"""启动加载 + fail-fast 校验（重写 §3.2）。

校验失败抛 ``ConfigurationError``，进程退出；禁止任何代码兜底目录。
"""

from __future__ import annotations

from bdlh_runtime.runtime.errors import ConfigurationError

from .models import VALID_TOPICS, RegistrySnapshot
from .store import RegistryStore


def load_and_validate(store: RegistryStore) -> RegistrySnapshot:
    """加载目录行并执行全部启动校验；任一失败即拒绝启动。"""
    snapshot = store.load()
    _validate_capabilities(snapshot)
    _validate_skills(snapshot)
    _validate_entitlements(snapshot)
    _validate_fastpath(snapshot)
    _validate_topic_capabilities(snapshot)
    if snapshot.budget_for("default") is None:
        raise ConfigurationError("registry: budget profile 'default' is missing")
    return snapshot


def _validate_capabilities(snapshot: RegistrySnapshot) -> None:
    if not snapshot.capabilities:
        # 硬规则 7：零 capability 行拒绝启动，禁止代码兜底
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
            # v1：read_only=false 的能力不得启用
            raise ConfigurationError(f"registry: capability {cap.name} is writable and enabled")


def _validate_skills(snapshot: RegistrySnapshot) -> None:
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
            outside = required_ops - snapshot.runtime_allowlist
            if outside:
                raise ConfigurationError(
                    f"registry: enabled skill {skill.skill_id} required operations "
                    f"outside runtime allowlist: {sorted(outside)}"
                )


def _validate_entitlements(snapshot: RegistrySnapshot) -> None:
    if not any(item.account_id == "*" for item in snapshot.entitlements):
        raise ConfigurationError("registry: default entitlement (account_id='*') is missing")
    known_ops = {op.code for op in snapshot.operations}
    unknown = {item.operation_code for item in snapshot.entitlements} - known_ops
    if unknown:
        raise ConfigurationError(f"registry: entitlement references unknown operations {sorted(unknown)}")


def _validate_fastpath(snapshot: RegistrySnapshot) -> None:
    names = {route.name for route in snapshot.fastpath_routes}
    allowed = {"chitchat", "knowledge", "forbidden"}
    if names != allowed:
        raise ConfigurationError(f"registry: fastpath routes must be exactly {sorted(allowed)}, got {sorted(names)}")
    for route in snapshot.fastpath_routes:
        if not route.utterances:
            raise ConfigurationError(f"registry: fastpath route {route.name} has no utterances")


def _validate_topic_capabilities(snapshot: RegistrySnapshot) -> None:
    if not snapshot.topic_capabilities:
        raise ConfigurationError("registry: topic capability mapping is empty")
    known_caps = {cap.name for cap in snapshot.capabilities if cap.enabled}
    for topic in VALID_TOPICS:
        caps = snapshot.topic_capabilities_for(topic)
        if not caps:
            raise ConfigurationError(f"registry: topic {topic} has no capability mapping")
    for record in snapshot.topic_capabilities:
        if record.topic not in VALID_TOPICS:
            raise ConfigurationError(f"registry: unknown topic {record.topic}")
        if record.capability_name not in known_caps:
            raise ConfigurationError(
                f"registry: topic {record.topic} references disabled/unknown capability {record.capability_name}"
            )
