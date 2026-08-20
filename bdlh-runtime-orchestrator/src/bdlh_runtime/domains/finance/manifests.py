"""Finance Domain 的自描述契约声明（ADR-010 §6）。

本模块声明 finance 域**当前的**真实状态：一份 ``DomainDescriptor`` + 三份
``SkillManifest``。声明即现状——只有 ``stock-research`` 端到端跑通，另外两个
Skill 的契约、授权与 builder 已存在但被 ``FinanceRuntime.run()`` 的
``ACTION_NOT_ENABLED`` 门拦住（runtime.py:124），因此标记为 ``FOUNDATION``。

关键防漂移设计（ADR-010 §3.1.4）：``required_capabilities`` 不手抄，直接从
Registry（库表 bdlh_runtime_capability_operation 派生）
派生。这样授权策略与 manifest 永远同源——改授权必须同步改 manifest，反之亦然。

本模块位于 ``domains/finance/`` 下，可以 import finance 契约；但它不 import
``tools``（能力名是字符串，启动时由 ``runtime/manifest_validation.py`` 校验）。
"""

from __future__ import annotations

from bdlh_runtime.domains.contracts import DomainOperation
from bdlh_runtime.domains.manifests import (
    DomainDescriptor,
    SkillManifest,
)
from bdlh_runtime.tools.capabilities import ToolsetName

from .contracts import FinancialIntent
from .snapshot_builder import PORTFOLIO_VALUATION_CAPABILITY

# ── 能力名派生：从 Registry（库表真源）反查，不维护第二份映射 ────────────────


def _capabilities_for(registry, *operations: DomainOperation) -> frozenset[str]:
    """从 Registry 派生：required_operations ⊆ 给定操作集合的全部能力名。"""
    granted = set(operations)
    return frozenset(
        spec.name for spec in registry.list() if spec.operations and set(spec.operations).issubset(granted)
    )


def build_skill_manifests(registry):
    """从 Registry 现算三份 SkillManifest 的能力清单（重写 §6.1：读库）。"""
    m1 = _capabilities_for(
        registry,
        DomainOperation.READ_MARKET_DATA,
        DomainOperation.RUN_ANALYSIS,
    )
    public_research = _capabilities_for(registry, DomainOperation.READ_PUBLIC_RESEARCH)
    m3 = _capabilities_for(
        registry,
        DomainOperation.READ_PORTFOLIO,
        DomainOperation.READ_PROFILE,
    )
    valuation = frozenset({PORTFOLIO_VALUATION_CAPABILITY})
    return m1, public_research, m3, valuation


# ── 三份 SkillManifest（声明现状；能力清单由 build_xxx(registry) 现算） ──────


def _stock_research_manifest(m1, public_research) -> SkillManifest:
    return SkillManifest(
        # 身份
        skill_id="stock-research",
        skill_version="stock-research.v1",
        domain="finance",
        status="CURRENT",
        # 输入
        request_contract="FinancialDomainRequest",
        accepted_intents=frozenset({FinancialIntent.STOCK_RESEARCH}),
        input_constraints=("instrument_count == 1",),
        # 输出
        result_contract="StockResearchResult",
        authority_field="stock_research_result",
        # 权限
        required_operations=frozenset(
            {
                DomainOperation.READ_MARKET_DATA,
                DomainOperation.RUN_ANALYSIS,
            }
        ),
        optional_operations=frozenset({DomainOperation.READ_PUBLIC_RESEARCH}),
        # 工具面
        required_toolsets=frozenset(
            {
                ToolsetName.MARKET_READ,
                ToolsetName.FUNDAMENTAL_READ,
                ToolsetName.PLANNING_COMPUTE,
            }
        ),
        required_capabilities=m1,
        optional_capabilities=public_research,
        # 数据条件：客观研究对 data_mode 无强约束（可基于行情/LIVE 数据）
        required_data_modes=frozenset({"LIVE", "USER_CONFIRMED", "TEST_FIXTURE"}),
        completeness_policy="coverage_downgrade_on_missing_evidence",
        # 预算
        budget_profile="DomainBudget.default",
        # 降级
        degradation_rules=(
            "missing_evidence -> PARTIAL + limitation",
            "all_evidence_missing -> LIMITED",
        ),
        on_missing_optional="SKIP_WITH_LIMITATION",
        on_budget_exhausted="FAILED + BUDGET_EXHAUSTED",
        # 幂等
        idempotency_keys=frozenset({"request_id", "instruments[0].symbol", "goal_ids"}),
        side_effects=frozenset(),
        # 观测
        audit_codes=frozenset({"STOCK_RESEARCH_EXECUTED"}),
        stable_error_codes=frozenset(
            {
                "ACTION_NOT_ENABLED",
                "FINANCE_REQUEST_INVALID",
                "REQUIRED_CAPABILITY_NOT_AUTHORIZED",
                "BUDGET_EXHAUSTED",
                "CAPABILITY_CONTRACT_VIOLATION",
                "STOCK_RESEARCH_BUILD_FAILED",
                "ANALYSIS_FAILED",
                "CAPABILITY_UNAVAILABLE",
            }
        ),
    )


def _portfolio_health_manifest(m3, valuation) -> SkillManifest:
    return SkillManifest(
        # 身份
        skill_id="portfolio-health",
        skill_version="portfolio-health.v1",
        domain="finance",
        status="FOUNDATION",  # 契约+授权+builder 存在，runtime 未启用
        # 输入
        request_contract="FinancialDomainRequest",
        accepted_intents=frozenset({FinancialIntent.PORTFOLIO_IMPACT}),
        input_constraints=("authenticated_user_id required",),
        # 输出
        result_contract="PortfolioImpact",
        authority_field="portfolio_impact",
        # 权限
        required_operations=frozenset(
            {
                DomainOperation.READ_PORTFOLIO,
                DomainOperation.READ_PROFILE,
            }
        ),
        optional_operations=frozenset(),
        # 工具面
        required_toolsets=frozenset(
            {
                ToolsetName.PORTFOLIO_READ,
                ToolsetName.FINANCIAL_PROFILE_READ,
            }
        ),
        required_capabilities=m3 | valuation,
        optional_capabilities=frozenset(),
        # 数据条件：拒绝 MOCK/UNAVAILABLE 驱动真实结论
        required_data_modes=frozenset({"LIVE", "USER_CONFIRMED"}),
        completeness_policy="fail_closed_on_missing_user_facts",
        # 预算
        budget_profile="DomainBudget.default",
        # 降级
        degradation_rules=(
            "missing_positions -> FAILED + SNAPSHOT_IDENTITY_MISMATCH",
            "missing_valuation -> PARTIAL with untrusted market_value warning",
        ),
        on_missing_optional="SKIP_WITH_LIMITATION",
        on_budget_exhausted="FAILED + BUDGET_EXHAUSTED",
        # 幂等
        idempotency_keys=frozenset({"request_id", "authenticated_user_id"}),
        side_effects=frozenset(),
        # 观测
        audit_codes=frozenset({"PORTFOLIO_HEALTH_EVALUATED"}),
        stable_error_codes=frozenset(
            {
                "ACTION_NOT_ENABLED",
                "SNAPSHOT_IDENTITY_MISMATCH",
                "FINANCIAL_SNAPSHOT_BUILD_FAILED",
                "PORTFOLIO_VALUATION_BUILD_FAILED",
            }
        ),
    )


def _suitability_manifest(m1, m3, valuation, public_research) -> SkillManifest:
    return SkillManifest(
        # 身份
        skill_id="suitability-evaluation",
        skill_version="suitability-evaluation.v1",
        domain="finance",
        status="FOUNDATION",  # 契约+授权+engine 占位存在，runtime 未启用
        # 输入
        request_contract="FinancialDomainRequest",
        accepted_intents=frozenset({FinancialIntent.SUITABILITY}),
        input_constraints=("instrument_count >= 1",),
        # 输出
        result_contract="SuitabilityAssessment",
        authority_field="suitability",
        # 权限
        required_operations=frozenset(
            {
                DomainOperation.READ_MARKET_DATA,
                DomainOperation.READ_PORTFOLIO,
                DomainOperation.READ_PROFILE,
                DomainOperation.RUN_ANALYSIS,
            }
        ),
        optional_operations=frozenset({DomainOperation.READ_PUBLIC_RESEARCH}),
        # 工具面
        required_toolsets=frozenset(
            {
                ToolsetName.MARKET_READ,
                ToolsetName.FUNDAMENTAL_READ,
                ToolsetName.PORTFOLIO_READ,
                ToolsetName.FINANCIAL_PROFILE_READ,
                ToolsetName.PLANNING_COMPUTE,
            }
        ),
        required_capabilities=m1 | m3 | valuation,
        optional_capabilities=public_research,
        # 数据条件：必须排除 MOCK/UNAVAILABLE（ADR-010 §3 示例）
        required_data_modes=frozenset({"LIVE", "USER_CONFIRMED"}),
        completeness_policy="INSUFFICIENT_INFORMATION_on_data_gap",
        # 预算
        budget_profile="DomainBudget.default",
        # 降级
        degradation_rules=(
            "insufficient_user_facts -> result=INSUFFICIENT_INFORMATION",
            "missing_research_coverage -> result=INSUFFICIENT_INFORMATION",
        ),
        on_missing_optional="SKIP_WITH_LIMITATION",
        on_budget_exhausted="FAILED + BUDGET_EXHAUSTED",
        # 幂等
        idempotency_keys=frozenset(
            {
                "request_id",
                "authenticated_user_id",
                "instruments[0].symbol",
            }
        ),
        side_effects=frozenset(),
        # 观测
        audit_codes=frozenset({"SUITABILITY_EVALUATED"}),
        stable_error_codes=frozenset(
            {
                "ACTION_NOT_ENABLED",
                "SUITABILITY_RESEARCH_PROFILE_REQUIRED",
                "INSUFFICIENT_INFORMATION",
            }
        ),
    )


# ── DomainDescriptor ─────────────────────────────────────────────────────────


def build_finance_descriptor(registry) -> DomainDescriptor:
    m1, public_research, m3, valuation = build_skill_manifests(registry)
    return DomainDescriptor(
        domain="finance",
        descriptor_version="finance-v1",
        status="CURRENT",
        # supported_intents：契约层声明的全部意图（FinancialIntent 4 个）
        supported_intents=frozenset(
            {
                FinancialIntent.STOCK_RESEARCH,
                FinancialIntent.SUITABILITY,
                FinancialIntent.PORTFOLIO_IMPACT,
                FinancialIntent.GOAL_PLANNING,
            }
        ),
        # enabled_intents：忠于 runtime.py:124 的 ACTION_NOT_ENABLED 门——
        # 当前只有 STOCK_RESEARCH 端到端跑通。其余意图返回稳定失败，不静默降级。
        enabled_intents=frozenset({FinancialIntent.STOCK_RESEARCH}),
        skills=(
            _stock_research_manifest(m1, public_research),
            _portfolio_health_manifest(m3, valuation),
            _suitability_manifest(m1, m3, valuation, public_research),
        ),
        request_contract="FinancialDomainRequest",
        outcome_contract="FinancialDomainOutcome",
    )
