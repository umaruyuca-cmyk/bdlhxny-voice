"""Guardrail 能力白名单装配助手。

产品装配路径以 ``registry.menu`` 的 eligible→allowed 为准
（见 ``runtime.application``）。本函数仅用于「Registry 全集 + Feature Flag」
的轻量白名单，供单测与兼容调用。
"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.contracts.capability_ids import DEEP_SEARCH_CAPABILITY


def authorized_capabilities_from_registry(
    capability_registry: Any,
    *,
    deep_research_enabled: bool = False,
    deep_research_infra_ready: bool = False,
) -> frozenset[str]:
    """从 Capability Registry 构造本轮 Guardrail 能力白名单。

    ``research.deep_search`` 仅在 Flag + 原子搜索基础设施同时就绪时纳入（G6）。
    白名单非空后 Plan/Action 的深度研究门禁才会生效（空集仍表示未装配，兼容旧单测）。
    """

    names = {spec.name for spec in capability_registry.list()}
    if deep_research_enabled and deep_research_infra_ready:
        names.add(DEEP_SEARCH_CAPABILITY)
    else:
        names.discard(DEEP_SEARCH_CAPABILITY)
    return frozenset(names)
