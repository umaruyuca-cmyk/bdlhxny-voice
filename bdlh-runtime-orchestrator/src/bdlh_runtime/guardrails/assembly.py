"""Guardrail 运行时白名单装配。"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.contracts.capability_ids import DEEP_SEARCH_CAPABILITY


def authorized_capabilities_from_registry(
    capability_registry: Any,
    *,
    deep_research_enabled: bool = False,
) -> frozenset[str]:
    """从 Capability Registry 构造本轮 Guardrail 能力白名单。

    ``research.deep_search`` 仅在 Deep Research 开关打开时纳入；白名单非空后
    Plan/Action 的深度研究门禁才会生效（空集仍表示未装配，兼容旧单测）。
    """

    names = {spec.name for spec in capability_registry.list()}
    if deep_research_enabled:
        names.add(DEEP_SEARCH_CAPABILITY)
    else:
        names.discard(DEEP_SEARCH_CAPABILITY)
    return frozenset(names)
