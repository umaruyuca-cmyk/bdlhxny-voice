"""Skill 与 Domain 的自描述契约模型（ADR-010）。

``SkillManifest`` / ``DomainDescriptor`` 是 Registry Snapshot 的运行时视图模型；
实例数据必须由 Snapshot 投影，不得在业务代码中手抄 Capability/Operation/Toolset。

纯净度约束（ADR-009 §3.3）：本模块只允许依赖 ``domains.contracts``（通用
``DomainOperation``）。能力名、Toolset 名一律以字符串形式声明，启动时由
``runtime/manifest_validation.py`` 对 Capability Registry 逐项校验。

``accepted_intents`` / ``supported_intents`` / ``enabled_intents`` 保留为空兼容槽，
不再用于业务分流（ADR-010：不以 intent 路由）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from bdlh_runtime.domains.contracts import DomainOperation

# 架构 §0.2 的状态标记；manifest 与 descriptor 共用同一组词汇。
ManifestStatus = Literal["CURRENT", "FOUNDATION", "TARGET", "EXPERIMENTAL", "RETIRED"]


@dataclass(frozen=True)
class SkillManifest:
    """单个 Skill 的自描述契约（ADR-010 §3 冻结字段表）。

    所有字段在发布后视为稳定契约：``skill_id`` 不得复用为其他语义，
    规则或输出结构变化必须递增 ``skill_version``。``side_effects`` 在 v1
    必须为空（只读），写副作用需单独 ADR 审查。
    """

    # ── 身份 ──
    skill_id: str
    skill_version: str
    domain: str
    status: ManifestStatus

    # ── 输入 ──
    request_contract: str
    """指向严格 Pydantic 模型名，如 ``"FinancialDomainRequest"``。"""
    accepted_intents: frozenset[str]
    """已废弃作路由；应为空集。业务路径不按意图分流。"""
    input_constraints: tuple[str, ...]
    """结构化约束；禁止自由文本。"""

    # ── 输出 ──
    result_contract: str
    authority_field: str
    """Outcome 上的权威载荷字段路径，杜绝双源真相（ADR-010 §2）。"""

    # ── 权限 ──
    required_operations: frozenset[DomainOperation]
    """精确 DomainOperation 集合；禁止前缀授权。"""
    optional_operations: frozenset[DomainOperation]
    """缺失时降级而非失败。"""

    # ── 工具面 ──
    required_toolsets: frozenset[str]
    """Toolset 名集合；必须存在于派生视图。"""
    required_capabilities: frozenset[str]
    """精确 Capability 名；启动时逐项对 Registry 校验（fail-fast）。"""
    optional_capabilities: frozenset[str]

    # ── 数据条件 ──
    required_data_modes: frozenset[str]
    """``data_mode`` 集合；例：Suitability 排除 ``MOCK / UNAVAILABLE``。"""
    completeness_policy: str
    """关键字段缺失时的稳定行为。"""

    # ── 预算（引用 DomainBudget 默认值，不内联第二套预算模型）──
    budget_profile: str

    # ── 降级 ──
    degradation_rules: tuple[str, ...]
    """映射到既有 ``PARTIAL / LIMITED / FAILED``。"""
    on_missing_optional: str
    """如 ``"SKIP_WITH_LIMITATION"``。"""
    on_budget_exhausted: str
    """必须能表达「不做部分抽样」。"""

    # ── 幂等 ──
    idempotency_keys: frozenset[str]
    """至少覆盖 ``request_id``。"""
    side_effects: frozenset[str] = field(default_factory=frozenset)
    """v1 必须为空 = 只读；写能力将来必须显式声明并单独审查。"""

    # ── 观测 ──
    audit_codes: frozenset[str] = field(default_factory=frozenset)
    """供 Guardrail 与日志断言的稳定码。"""
    stable_error_codes: frozenset[str] = field(default_factory=frozenset)
    """稳定错误码进 manifest，避免散落在实现里。"""
    enabled: bool = True
    """来自 Registry Skill.enabled；非 intent 路由。"""


@dataclass(frozen=True)
class DomainDescriptor:
    """Domain 的自描述契约（ADR-010 §4 冻结字段表）。

    Dispatcher 通过 descriptor 完成按 domain 分发；启用态以 Registry
    Skill.enabled 为准，不再用 ``enabled_intents`` 做业务分流。
    """

    domain: str
    """稳定小写标识，如 ``"finance"``。"""
    descriptor_version: str
    status: ManifestStatus
    skills: tuple[SkillManifest, ...]
    """该域下从 Registry 投影出的 SkillManifest 列表。"""
    request_contract: str
    outcome_contract: str
    supported_intents: frozenset[str] = field(default_factory=frozenset)
    """已废弃作路由；保留空集兼容。"""
    enabled_intents: frozenset[str] = field(default_factory=frozenset)
    """已废弃作路由；启用态以 Registry Skill.enabled 为准。"""
