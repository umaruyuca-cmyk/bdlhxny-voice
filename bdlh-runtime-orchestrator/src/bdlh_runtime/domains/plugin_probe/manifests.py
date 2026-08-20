"""M7 编译期 Manifest；声明实验性契约探针的真实边界。"""

from __future__ import annotations

from bdlh_runtime.domains.contracts import DomainOperation
from bdlh_runtime.domains.manifests import DomainDescriptor, SkillManifest

from .capability import PLUGIN_PROBE_CAPABILITY
from .contracts import PLUGIN_PROBE_INTENT

PLUGIN_PROBE_MANIFEST = SkillManifest(
    skill_id="plugin-contract-probe",
    skill_version="plugin-contract-probe.v1",
    domain="plugin_probe",
    status="EXPERIMENTAL",
    request_contract="PluginProbeRequest",
    accepted_intents=frozenset({PLUGIN_PROBE_INTENT}),
    input_constraints=("probe_ref ~= ^probe:[a-z0-9][a-z0-9._-]{0,63}$",),
    result_contract="PluginProbeResult",
    authority_field="result",
    required_operations=frozenset({DomainOperation.RUN_ANALYSIS}),
    optional_operations=frozenset(),
    required_toolsets=frozenset({"plugin_probe_compute"}),
    required_capabilities=frozenset({PLUGIN_PROBE_CAPABILITY}),
    optional_capabilities=frozenset(),
    required_data_modes=frozenset({"TEST_FIXTURE"}),
    completeness_policy="single deterministic observation required",
    budget_profile="DomainBudget.m7_contract_probe",
    degradation_rules=("contract violation -> FAILED",),
    on_missing_optional="SKIP_WITH_LIMITATION",
    on_budget_exhausted="FAILED + PROBE_BUDGET_INVALID",
    idempotency_keys=frozenset({"request_id", "probe_ref"}),
    side_effects=frozenset(),
    audit_codes=frozenset({"PLUGIN_PROBE_EXECUTED"}),
    stable_error_codes=frozenset(
        {
            "ACTION_NOT_ENABLED",
            "PROBE_REQUEST_CONTRACT_INVALID",
            "PROBE_OPERATION_NOT_AUTHORIZED",
            "PROBE_BUDGET_INVALID",
        }
    ),
)


PLUGIN_PROBE_DESCRIPTOR = DomainDescriptor(
    domain="plugin_probe",
    descriptor_version="plugin-probe.v1",
    status="EXPERIMENTAL",
    supported_intents=frozenset({PLUGIN_PROBE_INTENT}),
    enabled_intents=frozenset({PLUGIN_PROBE_INTENT}),
    skills=(PLUGIN_PROBE_MANIFEST,),
    request_contract="PluginProbeRequest",
    outcome_contract="PluginProbeOutcome",
)
