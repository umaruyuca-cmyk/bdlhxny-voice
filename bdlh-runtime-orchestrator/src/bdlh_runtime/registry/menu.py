"""菜单算法：effective_operations / eligible / allowed / 窗口（重写 §5）。

纯函数、无 LLM、无 I/O；输入 ``RegistrySnapshot`` 与运行期上下文。
LLM、goals[]、用户原句均不参与资格计算（硬规则 1）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import CapabilityRecord, RegistrySnapshot, SkillRecord

#: 窗口扁平分支阈值（n <= N 时全量列出）
FLAT_WINDOW_LIMIT = 20


def enabled_skills(snapshot: RegistrySnapshot) -> list[SkillRecord]:
    return [skill for skill in snapshot.skills if skill.enabled]


def effective_operations(
    snapshot: RegistrySnapshot,
    *,
    runtime_id: str = "default",
    account_id: str = "*",
) -> set[str]:
    """四层收窄的交集。skill 的 required 与 optional 行均并入——
    只并 required 会让 optional 证（如 READ_PUBLIC_RESEARCH）永远无效。"""
    del runtime_id  # 当前只有 default runtime；参数保留以对齐 DDL
    skill_ops: set[str] = set()
    for skill in enabled_skills(snapshot):
        # declared_operations 已并入 required + optional
        skill_ops |= skill.declared_operations
    entitled = {
        item.operation_code
        for item in snapshot.entitlements
        if item.account_id in {account_id, "*"}
    }
    return snapshot.runtime_allowlist & skill_ops & entitled


def eligible_capabilities(
    snapshot: RegistrySnapshot,
    effective_ops: set[str],
) -> list[CapabilityRecord]:
    """eligible = enabled ∧ read_only ∧ required_operations ⊆ effective_ops
    ∧ 属于至少一个 enabled skill 的 required/optional caps。"""
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
    return [
        cap
        for cap in eligible
        if (not cap.requires_authenticated_user) or authenticated
    ]


#: Feature Flag 门控能力（ADR-016）：Flag 关闭时不得进入本轮 allowed
FEATURE_GATED_CAPABILITIES = frozenset({"research.deep_search"})


def apply_feature_gates(
    allowed: list[CapabilityRecord],
    *,
    deep_research_enabled: bool = False,
) -> list[CapabilityRecord]:
    """按运行期 Feature Flag 从 allowed 中剔除未开放能力。"""
    if deep_research_enabled:
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


@dataclass(frozen=True)
class ToolWindow:
    """提示词窗口的可审计状态（重写 §4）。"""

    allowed_hash: str
    visible_toolsets: list[str]
    visible_capabilities: list[str]
    expansion_reason: str
    generation: int = 1


def build_window(
    snapshot: RegistrySnapshot,
    allowed: list[CapabilityRecord],
    *,
    generation: int = 1,
    expansion_reason: str = "flat",
) -> ToolWindow:
    """窗口构建：n <= 20 扁平列出全部；超过则按 toolset 折叠（首版不走向量）。"""
    import hashlib

    allowed_names = sorted(cap.name for cap in allowed)
    digest = hashlib.sha256("|".join(allowed_names).encode("utf-8")).hexdigest()[:16]
    if len(allowed) <= FLAT_WINDOW_LIMIT:
        visible_caps = allowed_names
        visible_toolsets: list[str] = []
        reason = expansion_reason if len(allowed) <= FLAT_WINDOW_LIMIT else "flat"
    else:
        # 折叠：先给组名；Agent 通过 OPEN_TOOLSET 展开该组中属于 allowed 的能力
        visible_toolsets = sorted({name for cap in allowed for name in cap.toolsets})
        visible_caps = allowed_names  # 窗口仍记录全量 allowed，呈现层只给组名
        reason = "toolset_folded"
    return ToolWindow(
        allowed_hash=digest,
        visible_toolsets=visible_toolsets,
        visible_capabilities=visible_caps,
        expansion_reason=reason,
        generation=generation,
    )
