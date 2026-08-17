"""M7 第二 Domain 的严格边界契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from bdlh_runtime.contracts.observation import Observation
from bdlh_runtime.domains.contracts import (
    DomainContractModel,
    DomainOutcome,
    DomainRequest,
)


PLUGIN_PROBE_INTENT = "CONTRACT_PROBE"


class PluginProbeRequest(DomainRequest):
    """只接受受控引用，不承载自由文本业务请求。"""

    domain: Literal["plugin_probe"] = "plugin_probe"
    intent: Literal["CONTRACT_PROBE"] = "CONTRACT_PROBE"
    probe_ref: str = Field(pattern=r"^probe:[a-z0-9][a-z0-9._-]{0,63}$")
    observed_at: datetime

    @model_validator(mode="after")
    def validate_probe_time(self) -> "PluginProbeRequest":
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return self


class PluginProbeResult(DomainContractModel):
    """权威探针结果，只说明哪些共享契约已被实际使用。"""

    probe_ref: str = Field(pattern=r"^probe:[a-z0-9][a-z0-9._-]{0,63}$")
    observation_ref: str = Field(min_length=1)
    reused_contracts: tuple[
        Literal[
            "DomainRequest",
            "DomainOutcome",
            "DomainBudget",
            "Observation",
            "Guardrail",
            "CapabilityRegistry",
        ],
        ...,
    ]


class PluginProbeOutcome(DomainOutcome):
    domain: Literal["plugin_probe"] = "plugin_probe"
    intent: Literal["CONTRACT_PROBE"] = "CONTRACT_PROBE"
    result: PluginProbeResult | None = None
    observation: Observation | None = None
    audit_codes: list[Literal["PLUGIN_PROBE_EXECUTED"]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_authority(self) -> "PluginProbeOutcome":
        if self.status == "COMPLETE":
            if self.result is None or self.observation is None:
                raise ValueError("COMPLETE plugin probe requires result and observation")
            if self.result.observation_ref != self.observation.observation_id:
                raise ValueError("plugin probe result must reference its Observation")
            if self.audit_codes != ["PLUGIN_PROBE_EXECUTED"]:
                raise ValueError("COMPLETE plugin probe requires its stable audit code")
        return self
