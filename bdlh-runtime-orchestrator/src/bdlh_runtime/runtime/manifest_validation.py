"""启动期 manifest ↔ Capability Registry 一致性校验（ADR-010）。

manifest 是 Registry Snapshot 的运行时投影；Capability Registry 是「有哪些能力」
的唯一真源。冲突时以 Registry 为准并使启动失败，不允许运行时静默跳过。

放在 ``runtime/`` 下（而非 ``domains/``）因为它需要同时依赖 ``tools`` 与
``domains``——校验职责上移到应用装配层以保持内核纯净度。
"""

from __future__ import annotations

from bdlh_runtime.domains.manifests import DomainDescriptor, SkillManifest
from bdlh_runtime.runtime.errors import ConfigurationError
from bdlh_runtime.tools.capabilities import CapabilityRegistry, ToolsetName


def validate_descriptor_against_registry(
    descriptor: DomainDescriptor,
    registry: CapabilityRegistry,
) -> None:
    """启动 fail-fast 校验。

    检查项（任一失败 → ``ConfigurationError``）：
      1. Skill 的 required/optional capabilities 必须在 Registry 中存在；
      2. required_toolsets 必须是合法 ToolsetName 或 Registry 已声明的 toolset；
      3. side_effects 必须为空（v1 只读）。
    """
    valid_toolsets = {member.value for member in ToolsetName}
    # Registry 投影出的 toolset 名也合法（plugin_probe 等非枚举 toolset）
    for skill in descriptor.skills:
        _validate_skill(skill, registry, valid_toolsets, descriptor.domain)


def _validate_skill(
    skill: SkillManifest,
    registry: CapabilityRegistry,
    valid_toolsets: set[str],
    domain: str,
) -> None:
    missing_capabilities = sorted(
        name for name in (skill.required_capabilities | skill.optional_capabilities) if not registry.contains(name)
    )
    if missing_capabilities:
        raise ConfigurationError(
            f"Skill {skill.skill_id!r} (domain={domain!r}) references unregistered "
            f"capabilities: {', '.join(missing_capabilities)}. "
            f"Manifest 与 Capability Registry 不一致（ADR-010 fail-fast）。"
        )

    # 允许 ToolsetName 枚举，或能力记录里已出现的 toolset 名
    registry_toolsets: set[str] = set()
    for spec in registry.list():
        registry_toolsets |= set(getattr(spec, "toolsets", ()) or ())
    allowed_toolsets = valid_toolsets | registry_toolsets
    invalid_toolsets = sorted(name for name in skill.required_toolsets if name not in allowed_toolsets)
    if invalid_toolsets:
        raise ConfigurationError(
            f"Skill {skill.skill_id!r} (domain={domain!r}) declares unknown "
            f"toolsets: {', '.join(invalid_toolsets)}. "
            f"合法值：{sorted(allowed_toolsets)}。"
        )

    if skill.side_effects:
        raise ConfigurationError(
            f"Skill {skill.skill_id!r} (domain={domain!r}) declares non-empty "
            f"side_effects={sorted(skill.side_effects)}. "
            f"v1 manifest 必须只读（ADR-010）；写副作用需单独 ADR 审查。"
        )
