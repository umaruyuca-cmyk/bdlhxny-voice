from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bdlh_runtime.contracts.observation import Observation
from bdlh_runtime.domains.contracts import DomainBudget, DomainOperation, DomainRequest
from bdlh_runtime.domains.dispatcher import DomainDispatcher
from bdlh_runtime.domains.plugin_probe import (
    PLUGIN_PROBE_DESCRIPTOR,
    PluginProbeOutcome,
    PluginProbeRequest,
    PluginProbeRuntime,
)
from bdlh_runtime.domains.registry import DomainRegistry
from bdlh_runtime.guardrails.contracts import GuardrailContext, GuardrailDecision
from bdlh_runtime.guardrails.policies import DefaultActionGuardrail, DefaultPlanGuardrail
from bdlh_runtime.cognitive.contracts import CognitiveAction, CognitiveActionType
from bdlh_runtime.runtime.manifest_validation import validate_descriptor_against_registry
from tests.helpers_registry import build_default_capability_registry


NOW = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


def request(
    *,
    operations: set[DomainOperation] | None = None,
    tool_calls: int = 0,
) -> PluginProbeRequest:
    return PluginProbeRequest(
        request_id="m7-request-1",
        authenticated_user_id="user-1",
        objective="验证第二 Domain 复用既有插件契约",
        authorized_operations=operations or {DomainOperation.RUN_ANALYSIS},
        budget=DomainBudget(
            tool_call_limit=tool_calls,
            runtime_seconds=5,
            model_call_limit=0,
        ),
        probe_ref="probe:m7-contract",
        observed_at=NOW,
    )


def dispatcher() -> DomainDispatcher:
    capabilities = build_default_capability_registry()
    register_plugin_probe_capability(capabilities)
    registry = DomainRegistry()
    registry.register("plugin_probe", PluginProbeRuntime(capabilities))
    registry.register_descriptor("plugin_probe", PLUGIN_PROBE_DESCRIPTOR)
    return DomainDispatcher(registry)


@pytest.mark.asyncio
async def test_second_domain_dispatches_through_the_existing_dispatcher() -> None:
    outcome = await dispatcher().dispatch(request())

    assert isinstance(outcome, PluginProbeOutcome)
    assert outcome.status == "COMPLETE"
    assert outcome.result is not None
    assert outcome.audit_codes == ["PLUGIN_PROBE_EXECUTED"]
    assert outcome.result.observation_ref == outcome.observation.observation_id
    assert isinstance(outcome.observation, Observation)
    assert set(outcome.result.reused_contracts) == {
        "DomainRequest",
        "DomainOutcome",
        "DomainBudget",
        "Observation",
        "Guardrail",
        "CapabilityRegistry",
    }


@pytest.mark.asyncio
async def test_probe_rejects_generic_request_instead_of_loosening_contract() -> None:
    generic = DomainRequest(
        request_id="generic",
        domain="plugin_probe",
        authenticated_user_id="user-1",
        objective="invalid",
        authorized_operations={DomainOperation.RUN_ANALYSIS},
        budget=DomainBudget(tool_call_limit=0, runtime_seconds=5),
    )

    outcome = await dispatcher().dispatch(generic)

    assert outcome.status == "FAILED"
    assert outcome.errors[0].code == "PROBE_REQUEST_CONTRACT_INVALID"


@pytest.mark.asyncio
async def test_probe_uses_shared_budget_and_operation_contracts() -> None:
    outcome = await dispatcher().dispatch(request(tool_calls=1))

    assert outcome.status == "FAILED"
    assert outcome.errors[0].code == "PROBE_BUDGET_INVALID"


def test_probe_manifest_validates_against_the_single_capability_registry() -> None:
    registry = build_default_capability_registry()
    before = tuple(registry.list())
    register_plugin_probe_capability(registry)

    validate_descriptor_against_registry(PLUGIN_PROBE_DESCRIPTOR, registry)

    assert len(registry.list()) == len(before) + 1
    assert registry.contains("plugin_probe.run_contract_check")
    assert PLUGIN_PROBE_DESCRIPTOR.status == "EXPERIMENTAL"
    assert PLUGIN_PROBE_DESCRIPTOR.enabled_intents == frozenset({"CONTRACT_PROBE"})
    assert PLUGIN_PROBE_DESCRIPTOR.skills[0].required_capabilities == frozenset(
        {"plugin_probe.run_contract_check"}
    )
    assert PLUGIN_PROBE_DESCRIPTOR.skills[0].side_effects == frozenset()


def test_probe_request_uses_the_existing_plan_and_action_guardrails() -> None:
    probe_request = request()
    action = CognitiveAction(
        action_type=CognitiveActionType.INVOKE_DOMAIN,
        reason_code="M7_CONTRACT_PROBE",
        reason="验证插件契约",
        domain_request=probe_request,
    )
    context = GuardrailContext(
        run_id=probe_request.request_id,
        authenticated_user_id="user-1",
        read_only=True,
        enabled_domains=frozenset({"plugin_probe"}),
        authorized_operations=frozenset({DomainOperation.RUN_ANALYSIS.value}),
        enabled_actions=frozenset({CognitiveActionType.INVOKE_DOMAIN.value}),
    )

    assert DefaultPlanGuardrail().evaluate_plan(action, context=context).decision == GuardrailDecision.ALLOW
    assert DefaultActionGuardrail().evaluate_action(action, context=context).decision == GuardrailDecision.ALLOW

    denied = context.model_copy(
        update={"enabled_domains": frozenset({"finance"})}
    )
    result = DefaultPlanGuardrail().evaluate_plan(action, context=denied)
    assert result.decision == GuardrailDecision.BLOCK
    assert result.audit_code == "DOMAIN_NOT_ENABLED"
