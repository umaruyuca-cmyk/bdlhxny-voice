"""Weather DomainDescriptor：从 Registry Snapshot 投影。"""

from __future__ import annotations

from bdlh_runtime.domains.contracts import DomainOperation
from bdlh_runtime.domains.manifests import DomainDescriptor, SkillManifest
from bdlh_runtime.registry.models import RegistrySnapshot, SkillRecord


def project_skill_manifest(skill: SkillRecord, snapshot: RegistrySnapshot) -> SkillManifest:
    del snapshot
    required_ops = frozenset(DomainOperation(code) for code, required in skill.operations if required)
    optional_ops = frozenset(DomainOperation(code) for code, required in skill.operations if not required)
    required_caps = frozenset(name for name, required in skill.capabilities if required)
    optional_caps = frozenset(name for name, required in skill.capabilities if not required)
    return SkillManifest(
        skill_id=skill.skill_id,
        skill_version=skill.skill_version,
        domain=skill.domain,
        status="EXPERIMENTAL",
        request_contract="DomainRequest",
        accepted_intents=frozenset(),
        input_constraints=(),
        result_contract="DomainOutcome",
        authority_field="established_facts",
        required_operations=required_ops,
        optional_operations=optional_ops,
        required_toolsets=frozenset(),
        required_capabilities=required_caps,
        optional_capabilities=optional_caps,
        required_data_modes=frozenset(),
        completeness_policy="toy_fixed_fixture",
        budget_profile="DomainBudget.default",
        degradation_rules=(),
        on_missing_optional="SKIP_WITH_LIMITATION",
        on_budget_exhausted="FAILED + BUDGET_EXHAUSTED",
        idempotency_keys=frozenset({"request_id"}),
        side_effects=frozenset(),
        audit_codes=frozenset(),
        stable_error_codes=frozenset(),
        enabled=skill.enabled,
    )


def build_weather_descriptor(snapshot: RegistrySnapshot) -> DomainDescriptor:
    skills = tuple(
        project_skill_manifest(skill, snapshot)
        for skill in sorted(
            (item for item in snapshot.skills if item.domain == "weather"),
            key=lambda item: item.skill_id,
        )
    )
    return DomainDescriptor(
        domain="weather",
        descriptor_version="weather-toy-v1",
        status="EXPERIMENTAL",
        supported_intents=frozenset(),
        enabled_intents=frozenset(),
        skills=skills,
        request_contract="DomainRequest",
        outcome_contract="DomainOutcome",
    )
