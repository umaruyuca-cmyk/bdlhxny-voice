"""Skill 与 Domain 的自描述契约模型（ADR-010）。

本模块是 ADR-010 冻结字段表的代码落点。``SkillManifest`` 描述单个 Skill 的
输入、输出、权限、工具面、数据条件、预算、降级、幂等与观测；``DomainDescriptor``
描述一个 Domain 声明支持哪些意图、当前启用哪些、挂载哪些 Skill。

纯净度约束（ADR-009 §3.3）：本模块只允许依赖 ``domains.contracts``（通用
``DomainOperation``）。它不得 import 任何领域实现（``domains.finance``）、
确定性引擎（``domain``）、供应商适配（``integrations``）或 Capability 实现
（``tools``）。能力名、Toolset 名、意图名一律以字符串形式声明，启动时由
``runtime/manifest_validation.py`` 对 Capability Registry 逐项校验。

manifest 是编译期注册的一等对象（Python 声明），不是运行时从磁盘/网络加载
的配置文件（ADR-010 §3.1.1）。
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
    """该 Skill 可处理的领域意图；空集表示不由意图触发。"""
    input_constraints: tuple[str, ...]
    """结构化约束，如 ``("instrument_count == 1",)``；禁止自由文本。"""

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


@dataclass(frozen=True)
class DomainDescriptor:
    """Domain 的自描述契约（ADR-010 §4 冻结字段表）。

    Dispatcher 通过 descriptor 完成路由与拒绝，因此**不需要 import 任何领域
    枚举**——``supported_intents`` / ``enabled_intents`` 都是字符串集合，
    ADR-009 §3.3 的内核纯净度得以保持。
    """

    domain: str
    """稳定小写标识，如 ``"finance"``。"""
    descriptor_version: str
    status: ManifestStatus
    supported_intents: frozenset[str]
    """该域声明可处理的意图集合。"""
    enabled_intents: frozenset[str]
    """当前实际启用的子集；未启用的意图必须返回 ``ACTION_NOT_ENABLED``（ADR-010 §5）。"""
    skills: tuple[SkillManifest, ...]
    """该域下的 SkillManifest 列表。"""
    request_contract: str
    outcome_contract: str
