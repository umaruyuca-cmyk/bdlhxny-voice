"""M7 插件对唯一 Capability Registry 的编译期增量注册。"""

from __future__ import annotations

from bdlh_runtime.tools.capabilities import (
    CapabilityRegistry,
    CapabilitySpec,
    ToolsetName,
)


PLUGIN_PROBE_CAPABILITY = "plugin_probe.run_contract_check"


def register_plugin_probe_capability(registry: CapabilityRegistry) -> None:
    """向应用的同一 Registry 实例注册探针；禁止创建插件私有 Registry。"""

    registry.register(
        CapabilitySpec(
            PLUGIN_PROBE_CAPABILITY,
            "执行无外部调用的插件契约一致性探针",
            "plugin_probe",
            "local",
            frozenset({"contract_probe"}),
            frozenset({"probe_ref", "observed_at"}),
            "Observation",
            timeout_seconds=5,
            toolsets=frozenset({ToolsetName.PLUGIN_PROBE_COMPUTE}),
        )
    )
