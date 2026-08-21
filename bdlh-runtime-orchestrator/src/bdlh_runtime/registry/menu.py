"""菜单算法：effective_operations / eligible / allowed / depends_on 闭包。

纯函数、无 LLM、无 I/O；输入 ``RegistrySnapshot`` 与运行期配置上下文。
LLM、goals[]、用户原句、requested_topics 均不参与资格计算。
交给 Agent 的是扁平 allowed 名单。
"""

from __future__ import annotations

from .defaults import DEFAULT_ENTITLEMENT_OPERATIONS, DEFAULT_RUNTIME_ALLOWED_OPERATIONS
from .models import CapabilityRecord, RegistrySnapshot, SkillRecord


def enabled_skills(snapshot: RegistrySnapshot) -> list[SkillRecord]:
    return [skill for skill in snapshot.skills if skill.enabled]


def effective_operations(
    snapshot: RegistrySnapshot,
    *,
    runtime_allowed: frozenset[str] | set[str] | None = None,
    entitlement: frozenset[str] | set[str] | None = None,
) -> set[str]:
    """effective = Runtime 允许 ∩ 已启用 Skill 声明 ∩ 默认 entitlement。"""
    runtime = set(runtime_allowed if runtime_allowed is not None else DEFAULT_RUNTIME_ALLOWED_OPERATIONS)
    entitled = set(entitlement if entitlement is not None else DEFAULT_ENTITLEMENT_OPERATIONS)
    skill_ops: set[str] = set()
    for skill in enabled_skills(snapshot):
        skill_ops |= skill.declared_operations
    return runtime & skill_ops & entitled


def eligible_capabilities(
    snapshot: RegistrySnapshot,
    effective_ops: set[str],
) -> list[CapabilityRecord]:
    """eligible = enabled ∧ read_only ∧ ops ⊆ effective ∧ 属于已启用 Skill。"""
    skill_caps: set[str] = set()
    for skill in enabled_skills(snapshot):
        skill_caps |= skill.declared_capabilities
    result: list[CapabilityRecord] = []
    for cap in snapshot.capabilities:
        if not cap.enabled or not cap.read_only:
            continue
        if not cap.operations.issubset(effective_ops):
            continue
        if cap.name not in skill_caps:
            continue
        result.append(cap)
    return sorted(result, key=lambda item: item.name)


def allowed_capabilities(
    eligible: list[CapabilityRecord],
    *,
    authenticated: bool,
) -> list[CapabilityRecord]:
    """allowed = eligible ∧ 认证状态满足 requires_authenticated_user。"""
    return [cap for cap in eligible if (not cap.requires_authenticated_user) or authenticated]


#: Feature Flag 门控能力（ADR-016）：Flag 关闭时不得进入本轮 allowed
FEATURE_GATED_CAPABILITIES = frozenset({"research.deep_search"})


def apply_feature_gates(
    allowed: list[CapabilityRecord],
    *,
    deep_research_enabled: bool = False,
    deep_research_infra_ready: bool = False,
) -> list[CapabilityRecord]:
    """按运行期 Feature Flag + 基础设施门禁从 allowed 中剔除未开放能力。

    ADR-016 / G6：Flag 不得掩盖缺百炼凭证等基础设施缺失；两者同时满足才保留
    ``research.deep_search``。
    """
    if deep_research_enabled and deep_research_infra_ready:
        return list(allowed)
    return [cap for cap in allowed if cap.name not in FEATURE_GATED_CAPABILITIES]


def dependency_closure(snapshot: RegistrySnapshot, names: list[str]) -> list[str]:
    """对给定能力做 depends_on 闭包（含自身），返回去重排序列表。"""
    by_name = {cap.name: cap for cap in snapshot.capabilities}
    seen: set[str] = set()
    stack = list(names)
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        cap = by_name.get(name)
        if cap is not None:
            stack.extend(cap.depends_on - seen)
    return sorted(seen)
