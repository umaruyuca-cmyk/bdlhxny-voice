"""SkillManifest / DomainDescriptor：Registry Snapshot 投影回归（ADR-010）。"""

from __future__ import annotations

import pytest
from tests.helpers_registry import build_default_capability_registry, seeded_snapshot

from bdlh_runtime.domains.finance.contracts import FinancialDomainOutcome
from bdlh_runtime.domains.finance.manifests import build_finance_descriptor
from bdlh_runtime.domains.registry import DomainRegistry

_SNAPSHOT = seeded_snapshot()
_REGISTRY = build_default_capability_registry()
FINANCE_DESCRIPTOR = build_finance_descriptor(_SNAPSHOT)
SKILLS = {skill.skill_id: skill for skill in FINANCE_DESCRIPTOR.skills}


def test_finance_descriptor_projects_skills_from_registry_snapshot() -> None:
    descriptor = FINANCE_DESCRIPTOR
    assert descriptor.domain == "finance"
    assert descriptor.status == "CURRENT"
    assert descriptor.enabled_intents == frozenset()
    assert descriptor.supported_intents == frozenset()
    assert set(SKILLS) == {
        "stock-research",
        "portfolio-health",
        "suitability-evaluation",
    }
    assert SKILLS["stock-research"].status == "CURRENT"
    assert SKILLS["portfolio-health"].status == "CURRENT"
    assert SKILLS["suitability-evaluation"].status == "FOUNDATION"


@pytest.mark.parametrize("skill_id", sorted(SKILLS))
def test_finance_manifests_are_side_effect_free(skill_id: str) -> None:
    assert SKILLS[skill_id].side_effects == frozenset()


def test_finance_manifest_capabilities_match_skill_records() -> None:
    """投影能力必须等于 Snapshot SkillRecord，不得手抄扩张。"""
    by_id = {skill.skill_id: skill for skill in _SNAPSHOT.skills if skill.domain == "finance"}
    for skill_id, manifest in SKILLS.items():
        record = by_id[skill_id]
        expected_required = {name for name, required in record.capabilities if required}
        expected_optional = {name for name, required in record.capabilities if not required}
        assert set(manifest.required_capabilities) == expected_required
        assert set(manifest.optional_capabilities) == expected_optional
        assert set(manifest.required_capabilities | manifest.optional_capabilities) <= {
            spec.name for spec in _REGISTRY.list()
        }


@pytest.mark.parametrize("skill_id", sorted(SKILLS))
def test_authority_field_points_to_real_outcome_slot(skill_id: str) -> None:
    outcome_fields = set(FinancialDomainOutcome.model_fields)
    assert SKILLS[skill_id].authority_field in outcome_fields


def test_portfolio_valuation_capability_is_registered() -> None:
    assert _REGISTRY.contains("portfolio.build_current_valuation")


def test_registry_registers_descriptor_and_queries_skill() -> None:
    registry = DomainRegistry()
    registry.register("finance", object())
    registry.register_descriptor("finance", FINANCE_DESCRIPTOR)

    assert registry.descriptor("finance") is FINANCE_DESCRIPTOR
    assert registry.is_skill_enabled("finance", "stock-research")
    assert registry.is_skill_enabled("finance", "portfolio-health")


def test_registry_rejects_descriptor_for_unregistered_domain() -> None:
    registry = DomainRegistry()
    with pytest.raises(ValueError, match="unregistered domain"):
        registry.register_descriptor("finance", FINANCE_DESCRIPTOR)


def test_registry_rejects_descriptor_domain_mismatch() -> None:
    registry = DomainRegistry()
    registry.register("other", object())
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
    assert not registry.is_skill_enabled("finance", "stock-research")
