"""M7 插件契约探针 Domain。

该包只验证第二 Domain 能复用既有跨层契约，不提供面向用户的业务能力。
"""

from .contracts import PluginProbeOutcome, PluginProbeRequest, PluginProbeResult
from .capability import PLUGIN_PROBE_CAPABILITY, register_plugin_probe_capability
from .manifests import PLUGIN_PROBE_DESCRIPTOR, PLUGIN_PROBE_MANIFEST
from .runtime import PluginProbeRuntime

__all__ = [
    "PLUGIN_PROBE_DESCRIPTOR",
    "PLUGIN_PROBE_CAPABILITY",
    "PLUGIN_PROBE_MANIFEST",
    "PluginProbeOutcome",
    "PluginProbeRequest",
    "PluginProbeResult",
    "PluginProbeRuntime",
    "register_plugin_probe_capability",
]
