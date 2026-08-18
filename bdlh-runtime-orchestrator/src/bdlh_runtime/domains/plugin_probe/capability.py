"""M7 插件探针能力名常量。

重写后探针能力只来自库表种子（bdlh_runtime_capability 行）；本模块仅保留
字符串常量供 Runtime/测试引用，不再向内存 Registry 注册硬编码 Spec。
"""

from __future__ import annotations

PLUGIN_PROBE_CAPABILITY = "plugin_probe.run_contract_check"
