"""M7 第二 Domain 的确定性、无外部副作用 Runtime。"""

from __future__ import annotations

from bdlh_runtime.contracts.observation import (
    DataQuality,
    Observation,
    ProvenanceRecord,
)
from bdlh_runtime.domains.contracts import (
    ConfidenceAssessment,
    DomainError,
    DomainFact,
    DomainOperation,
    DomainOutcome,
    DomainRequest,
)
from bdlh_runtime.tools.capabilities import CapabilityRegistry

from .contracts import PluginProbeOutcome, PluginProbeRequest, PluginProbeResult
from .capability import PLUGIN_PROBE_CAPABILITY


class PluginProbeRuntime:
    """证明第二 Domain 可注册和调度；不访问网络、模型、数据库或用户事实。"""

    def __init__(self, capability_registry: CapabilityRegistry) -> None:
        self._capabilities = capability_registry

    async def run(self, request: DomainRequest) -> DomainOutcome:
        if not isinstance(request, PluginProbeRequest):
            return self._failed(
                request,
                "PROBE_REQUEST_CONTRACT_INVALID",
                "plugin_probe requires PluginProbeRequest",
            )
        if DomainOperation.RUN_ANALYSIS not in request.authorized_operations:
            return self._failed(
                request,
                "PROBE_OPERATION_NOT_AUTHORIZED",
                "contract probe requires the shared RUN_ANALYSIS operation",
            )
        if (
            request.budget.tool_call_limit != 0
            or request.budget.model_call_limit != 0
        ):
            return self._failed(
                request,
                "PROBE_BUDGET_INVALID",
                "contract probe must use zero tool and model calls",
            )

        capability_name = PLUGIN_PROBE_CAPABILITY
        if not self._capabilities.contains(capability_name):
            return self._failed(
                request,
                "PROBE_CAPABILITY_NOT_REGISTERED",
                "contract probe capability is missing from the shared registry",
            )
        capability = self._capabilities.get(capability_name)
        if not capability.read_only or capability.adapter != "local":
            return self._failed(
                request,
                "PROBE_CAPABILITY_CONTRACT_INVALID",
                "contract probe capability must be local and read-only",
            )

        observation_id = f"observation:{request.request_id}"
        observation = Observation(
            observation_id=observation_id,
            capability=capability.name,
            status="SUCCESS",
            data={
                "data_mode": "TEST_FIXTURE",
                "probe_ref": request.probe_ref,
                "contract_version": "m7.v1",
            },
            data_quality=DataQuality(
                completeness=1.0,
                freshness="POINT_IN_TIME",
                quality_status="OK",
            ),
            provenance=[
                ProvenanceRecord(
                    source="plugin-probe-domain",
                    tool="deterministic-contract-probe",
                    request_id=request.request_id,
                    as_of=request.observed_at.isoformat(),
                    retrieved_at=request.observed_at.isoformat(),
                    elapsed_ms=0,
                    raw_reference=observation_id,
                )
            ],
        )
        result = PluginProbeResult(
            probe_ref=request.probe_ref,
            observation_ref=observation_id,
            reused_contracts=(
                "DomainRequest",
                "DomainOutcome",
                "DomainBudget",
                "Observation",
                "Guardrail",
                "CapabilityRegistry",
            ),
        )
        return PluginProbeOutcome(
            request_id=request.request_id,
            status="COMPLETE",
            result=result,
            observation=observation,
            established_facts=[
                DomainFact(
                    fact_id=f"fact:{request.request_id}",
                    statement="M7 plugin contract probe completed",
                    value=request.probe_ref,
                    source_refs=[observation_id],
                    directness="DIRECT",
                )
            ],
            confidence=ConfidenceAssessment(
                level="HIGH",
                reasons=["Deterministic contract probe completed without external calls"],
                coverage_status="COMPLETE",
            ),
            audit_codes=["PLUGIN_PROBE_EXECUTED"],
        )

    @staticmethod
    def _failed(request: DomainRequest, code: str, message: str) -> DomainOutcome:
        return DomainOutcome(
            request_id=request.request_id,
            domain=request.domain,
            status="FAILED",
            confidence=ConfidenceAssessment(
                level="LOW",
                reasons=[message],
                coverage_status="LIMITED",
            ),
            errors=[DomainError(code=code, message=message, retryable=False)],
            limitations=[message],
        )
