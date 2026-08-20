"""SkillManifest / DomainDescriptor 契约回归（ADR-010 §3/§4/§6）。

验证 finance 域的 descriptor 与三份 manifest **声明现状**而非未来蓝图，且与
授权映射、Capability Registry、Outcome 契约保持一致——防止双源漂移。
"""

from __future__ import annotations

import pytest
from tests.helpers_registry import build_default_capability_registry

from bdlh_runtime.domains.finance.contracts import (
    FinancialDomainOutcome,
    FinancialIntent,
)
from bdlh_runtime.domains.finance.manifests import build_finance_descriptor
from bdlh_runtime.domains.registry import DomainRegistry

# 重写：manifest 从 Registry（库表派生）现算，模块级常量已删
_registry = build_default_capability_registry()
FINANCE_DESCRIPTOR = build_finance_descriptor(_registry)
[STOCK_RESEARCH_MANIFEST, PORTFOLIO_HEALTH_MANIFEST, SUITABILITY_MANIFEST] = list(FINANCE_DESCRIPTOR.skills)


# ── descriptor 声明现状 ─────────────────────────────────────────────────────


def test_finance_descriptor_declares_current_reality() -> None:
    """enabled_intents 反映 runtime 已开放的意图门。"""
    descriptor = FINANCE_DESCRIPTOR

    assert descriptor.domain == "finance"
    assert descriptor.status == "CURRENT"
    assert descriptor.enabled_intents == frozenset(
        {FinancialIntent.STOCK_RESEARCH, FinancialIntent.SUITABILITY}
    )
    # supported_intents 覆盖契约层全部 4 个意图
    assert descriptor.supported_intents == frozenset(
        {
            FinancialIntent.STOCK_RESEARCH,
            FinancialIntent.SUITABILITY,
            FinancialIntent.PORTFOLIO_IMPACT,
            FinancialIntent.GOAL_PLANNING,
        }
    )
    assert descriptor.request_contract == "FinancialDomainRequest"
    assert descriptor.outcome_contract == "FinancialDomainOutcome"


def test_finance_descriptor_has_three_skills_with_correct_status() -> None:
    """三份 manifest 的 status 反映实现成熟度，不虚构。"""
    skills = {s.skill_id: s for s in FINANCE_DESCRIPTOR.skills}

    assert set(skills) == {
        "stock-research",
        "portfolio-health",
        "suitability-evaluation",
    }
    # 只有 stock-research 端到端跑通
    assert skills["stock-research"].status == "CURRENT"
    # 另外两个：契约+授权+builder 存在，runtime 未启用
    assert skills["portfolio-health"].status == "FOUNDATION"
    assert skills["suitability-evaluation"].status == "FOUNDATION"


# ── v1 只读硬规则 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "manifest",
    [STOCK_RESEARCH_MANIFEST, PORTFOLIO_HEALTH_MANIFEST, SUITABILITY_MANIFEST],
    ids=lambda m: m.skill_id,
)
def test_finance_manifests_are_side_effect_free(manifest) -> None:
    """ADR-010 §3：v1 manifest 必须只读，side_effects 为空。"""
    assert manifest.side_effects == frozenset(), f"{manifest.skill_id} 声明了 side_effects，违反 v1 只读硬规则"


# ── 防双源漂移：manifest 能力 vs 授权映射 ─────────────────────────────────


def test_finance_manifest_capabilities_match_authorization_map() -> None:
    """manifest 的能力名必须从 authorization.py 派生，不得手抄漂移。

    所有 manifest 的 required+optional capabilities 的并集，应等于
    FINANCE_OPERATION_CAPABILITIES 的并集加上域内派生能力（估值重算）。
    """

    # 重写：能力真源是 Registry（capability_operation 表派生）
    expected = frozenset(spec.name for spec in _registry.list())

    manifest_capabilities: set[str] = set()
    for skill in FINANCE_DESCRIPTOR.skills:
        manifest_capabilities |= skill.required_capabilities
        manifest_capabilities |= skill.optional_capabilities

    assert manifest_capabilities == expected, (
        "manifest 能力名与授权映射漂移："
        f"只在 manifest={sorted(manifest_capabilities - expected)}，"
        f"只在授权={sorted(expected - manifest_capabilities)}"
    )


# ── authority_field 指向真实 Outcome 字段 ─────────────────────────────────


@pytest.mark.parametrize(
    "manifest",
    [STOCK_RESEARCH_MANIFEST, PORTFOLIO_HEALTH_MANIFEST, SUITABILITY_MANIFEST],
    ids=lambda m: m.skill_id,
)
def test_authority_field_points_to_real_outcome_slot(manifest) -> None:
    """authority_field 必须是 FinancialDomainOutcome 上真实存在的字段。"""
    outcome_fields = set(FinancialDomainOutcome.model_fields)
    assert manifest.authority_field in outcome_fields, (
        f"{manifest.skill_id}.authority_field={manifest.authority_field!r} "
        f"不在 FinancialDomainOutcome 字段中：{sorted(outcome_fields)}"
    )


# ── M3 能力注册守护（Step 0 回归） ──────────────────────────────────────────


def test_portfolio_valuation_capability_is_registered() -> None:
    """Step 0 补注册的确定性估值能力必须在 Registry 可见。"""
    registry = build_default_capability_registry()
    assert registry.contains("portfolio.build_current_valuation")


# ── DomainRegistry descriptor 注册行为 ─────────────────────────────────────


def test_registry_registers_descriptor_and_queries_intent() -> None:
    """register_descriptor 存储 descriptor，is_intent_enabled 据此回答。"""
    registry = DomainRegistry()
    registry.register("finance", object())
    registry.register_descriptor("finance", FINANCE_DESCRIPTOR)

    assert registry.descriptor("finance") is FINANCE_DESCRIPTOR
    assert registry.is_intent_enabled("finance", FinancialIntent.STOCK_RESEARCH)
    assert registry.is_intent_enabled("finance", FinancialIntent.SUITABILITY)
    assert not registry.is_intent_enabled("finance", FinancialIntent.PORTFOLIO_IMPACT)


def test_registry_rejects_descriptor_for_unregistered_domain() -> None:
    registry = DomainRegistry()
    with pytest.raises(ValueError, match="unregistered domain"):
        registry.register_descriptor("finance", FINANCE_DESCRIPTOR)


def test_registry_rejects_descriptor_domain_mismatch() -> None:
    registry = DomainRegistry()
    registry.register("other", object())
    # descriptor.domain="finance" 但注册到 "other" —— 必须报不匹配
    with pytest.raises(ValueError, match="Descriptor domain mismatch"):
        registry.register_descriptor("other", FINANCE_DESCRIPTOR)


def test_registry_rejects_duplicate_descriptor() -> None:
    registry = DomainRegistry()
    registry.register("finance", object())
    registry.register_descriptor("finance", FINANCE_DESCRIPTOR)
    with pytest.raises(ValueError, match="already registered"):
        registry.register_descriptor("finance", FINANCE_DESCRIPTOR)


def test_registry_descriptor_none_when_not_registered() -> None:
    registry = DomainRegistry()
    assert registry.descriptor("finance") is None
    assert not registry.is_intent_enabled("finance", "ANY_INTENT")
