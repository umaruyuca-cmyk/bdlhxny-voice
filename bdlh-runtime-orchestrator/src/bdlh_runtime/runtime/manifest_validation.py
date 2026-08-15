"""启动期 manifest ↔ Capability Registry 一致性校验（ADR-010 §3.1.2）。

本模块是 ADR-010 「启动 fail-fast」规则的执行点。manifest 声明「Skill 需要哪些
能力」，Capability Registry 是「有哪些能力」的唯一真源；两者冲突时以 Registry
为准并使启动失败（ADR-010 §3.1.4），不允许运行时静默跳过。

放在 ``runtime/`` 下（而非 ``domains/``）因为它需要同时依赖 ``tools``（Capability
Registry）和 ``domains``（manifest 模型）——这恰好是内核纯净度门禁
（ADR-009 §3.3）禁止内核模块做的事，所以校验职责必须上移到应用装配层。
"""

from __future__ import annotations

from bdlh_runtime.domains.manifests import DomainDescriptor, SkillManifest
from bdlh_runtime.runtime.errors import ConfigurationError
from bdlh_runtime.tools.capabilities import CapabilityRegistry, ToolsetName


def validate_descriptor_against_registry(
    descriptor: DomainDescriptor,
    registry: CapabilityRegistry,
) -> None:
    """ADR-010 §3.1.2 启动 fail-fast 校验。

    检查项（任一失败 → ``ConfigurationError``，启动中止）：
      1. 每个 Skill 的 ``required_capabilities`` / ``optional_capabilities`` 中
         的能力名必须在 Registry 中存在；
      2. 每个 Skill 的 ``required_toolsets`` 必须是合法 ``ToolsetName``；
      3. 每个 Skill 的 ``side_effects`` 必须为空（v1 只读硬规则）；
      4. ``enabled_intents`` 中的每个 intent 至少有一个 Skill 的
         ``accepted_intents`` 声明它（ADR-010 §5：意图已启用但无 Skill 声明
         是配置错误，不留到运行时）。

    本函数只做声明层校验，不改变任何运行时行为。
    """
    valid_toolsets = {member.value for member in ToolsetName}

    for skill in descriptor.skills:
        _validate_skill(skill, registry, valid_toolsets, descriptor.domain)

    _validate_enabled_intents_have_skills(descriptor)


def _validate_skill(
    skill: SkillManifest,
    registry: CapabilityRegistry,
    valid_toolsets: set[str],
    domain: str,
) -> None:
    """校验单个 SkillManifest 的能力/工具集/只读约束。"""
    # 1. 能力名必须在 Registry 存在（required 与 optional 都查）
    missing_capabilities = sorted(
        name
        for name in (skill.required_capabilities | skill.optional_capabilities)
        if not registry.contains(name)
    )
    if missing_capabilities:
        raise ConfigurationError(
            f"Skill {skill.skill_id!r} (domain={domain!r}) references unregistered "
            f"capabilities: {', '.join(missing_capabilities)}. "
            f"Manifest 与 Capability Registry 不一致（ADR-010 §3.1.2 fail-fast）。"
        )

    # 2. required_toolsets 必须是合法 ToolsetName
    invalid_toolsets = sorted(
        name for name in skill.required_toolsets if name not in valid_toolsets
    )
    if invalid_toolsets:
        raise ConfigurationError(
            f"Skill {skill.skill_id!r} (domain={domain!r}) declares unknown "
            f"toolsets: {', '.join(invalid_toolsets)}. "
            f"合法值：{sorted(valid_toolsets)}。"
        )

    # 3. v1 只读硬规则：side_effects 必须为空
    if skill.side_effects:
        raise ConfigurationError(
            f"Skill {skill.skill_id!r} (domain={domain!r}) declares non-empty "
            f"side_effects={sorted(skill.side_effects)}. "
            f"v1 manifest 必须只读（ADR-010 §3）；写副作用需单独 ADR 审查。"
        )


def _validate_enabled_intents_have_skills(descriptor: DomainDescriptor) -> None:
    """ADR-010 §5：每个 enabled intent 必须有 Skill 声明处理它。"""
    # 收集所有 Skill 声明能处理的 intent
    declared_intents: set[str] = set()
    for skill in descriptor.skills:
        declared_intents |= skill.accepted_intents

    orphan_intents = sorted(
        intent
        for intent in descriptor.enabled_intents
        if intent not in declared_intents
    )
    if orphan_intents:
        raise ConfigurationError(
            f"Domain {descriptor.domain!r} 的 enabled_intents "
            f"{orphan_intents} 没有任何 Skill 的 accepted_intents 声明处理。"
            f"这是配置错误（ADR-010 §5）；请将该 intent 加入某 Skill 的 "
            f"accepted_intents，或从 enabled_intents 移除。"
        )
