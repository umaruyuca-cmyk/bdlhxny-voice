"""Finance DomainDescriptor / SkillManifest：仅从 Registry Snapshot 投影。

ADR-010：Capability / Operation / Toolset 清单不得在本模块手抄；
``accepted_intents`` 不再用于业务分流。结果权威字段映射只是 Outcome 槽位
接线，不是第二份能力目录。
"""

from __future__ import annotations

from bdlh_runtime.domains.contracts import DomainOperation
from bdlh_runtime.domains.manifests import DomainDescriptor, SkillManifest
from bdlh_runtime.registry.models import RegistrySnapshot, SkillRecord

# Outcome 权威字段：skill_id → (result_contract, authority_field)
_OUTCOME_SLOTS: dict[str, tuple[str, str]] = {
    "stock-research": ("StockResearchResult", "stock_research_result"),
    "portfolio-health": ("PortfolioImpact", "portfolio_impact"),
    "suitability-evaluation": ("SuitabilityAssessment", "suitability"),
}


def project_skill_manifest(skill: SkillRecord, snapshot: RegistrySnapshot) -> SkillManifest:
    """把一条 SkillRecord 投影为运行时 SkillManifest。"""
    required_ops = frozenset(DomainOperation(code) for code, required in skill.operations if required)
    optional_ops = frozenset(DomainOperation(code) for code, required in skill.operations if not required)
    required_caps = frozenset(name for name, required in skill.capabilities if required)
    optional_caps = frozenset(name for name, required in skill.capabilities if not required)
    toolsets: set[str] = set()
    for name in required_caps | optional_caps:
        record = snapshot.capability(name)
        if record is not None:
            toolsets |= set(record.toolsets)
    result_contract, authority_field = _OUTCOME_SLOTS.get(
        skill.skill_id,
        ("FinancialDomainOutcome", "stock_research_result"),
    )
    allowed_status = {"CURRENT", "FOUNDATION", "TARGET", "EXPERIMENTAL", "RETIRED"}
    status = skill.status if skill.status in allowed_status else "FOUNDATION"
    return SkillManifest(
        skill_id=skill.skill_id,
        skill_version=skill.skill_version,
        domain=skill.domain,
        status=status,  # type: ignore[arg-type]
        request_contract="FinancialDomainRequest",
        accepted_intents=frozenset(),
        input_constraints=(),
        result_contract=result_contract,
        authority_field=authority_field,
        required_operations=required_ops,
        optional_operations=optional_ops,
        required_toolsets=frozenset(toolsets),
        required_capabilities=required_caps,
        optional_capabilities=optional_caps,
        required_data_modes=frozenset({"LIVE", "USER_CONFIRMED"}),
        completeness_policy="registry_projected",
        budget_profile="DomainBudget.default",
        degradation_rules=(),
        on_missing_optional="SKIP_WITH_LIMITATION",
        on_budget_exhausted="FAILED + BUDGET_EXHAUSTED",
        idempotency_keys=frozenset({"request_id"}),
        side_effects=frozenset(),
        audit_codes=frozenset(),
        stable_error_codes=frozenset({"ACTION_NOT_ENABLED"}),
        enabled=skill.enabled,
    )


def build_finance_descriptor(snapshot: RegistrySnapshot) -> DomainDescriptor:
    """从 Registry Snapshot 投影 finance DomainDescriptor（无第二份能力清单）。"""
    skills = tuple(
        project_skill_manifest(skill, snapshot)
        for skill in sorted(
            (item for item in snapshot.skills if item.domain == "finance"),
            key=lambda item: item.skill_id,
        )
    )
    return DomainDescriptor(
        domain="finance",
        descriptor_version="finance-v1",
        status="CURRENT",
        supported_intents=frozenset(),
        enabled_intents=frozenset(),
        skills=skills,
        request_contract="FinancialDomainRequest",
        outcome_contract="FinancialDomainOutcome",
    )
