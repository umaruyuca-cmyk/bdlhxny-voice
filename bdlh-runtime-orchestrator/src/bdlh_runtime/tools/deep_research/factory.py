"""Deep Research 生产装配工厂（ADR-016 / G6）。

门禁：``BDLH_DEEP_RESEARCH_ENABLED`` 且原子搜索（百炼）已配置，才启用执行器。
Flag 打开但缺凭证时执行器保持关闭，且不得进入 allowed（由 apply_feature_gates 配合）。
"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.tools.deep_research.bailian_provider import BailianWebSearchProvider
from bdlh_runtime.tools.deep_research.executor import DeepResearchToolExecutor
from bdlh_runtime.tools.deep_research.models import LangchainDeepResearchModel, RuleBasedDeepResearchModel


def deep_research_infra_ready(settings: Any) -> bool:
    """原子搜索基础设施是否可支撑生产 Deep Research。"""
    key = (getattr(settings, "bailian_web_search_api_key", None) or "").strip()
    return bool(key)


def create_deep_research_executor(
    settings: Any,
    *,
    llm: Any | None = None,
    atomic_search: Any | None = None,
) -> DeepResearchToolExecutor:
    """装配 DeepResearchToolExecutor。

    - Flag 关或无原子搜索 → ``enabled=False``（UNAVAILABLE，不跑编排）
    - Flag 开且有百炼 Key（或显式注入 atomic_search）→ 启用
    """
    flag_on = bool(getattr(settings, "deep_research_enabled", False))
    provider = atomic_search
    if provider is None and flag_on:
        provider = BailianWebSearchProvider(
            api_key=getattr(settings, "bailian_web_search_api_key", None),
            endpoint=getattr(settings, "bailian_web_search_endpoint", None),
            timeout_seconds=float(getattr(settings, "bailian_web_search_timeout_seconds", 20.0) or 20.0),
            rate_limit_per_minute=int(
                getattr(settings, "bailian_web_search_rate_limit_per_minute", 30) or 30
            ),
        )
        if not getattr(provider, "configured", False):
            provider = None

    enabled = flag_on and provider is not None
    research_model: Any = RuleBasedDeepResearchModel()
    if enabled and llm is not None:
        research_model = LangchainDeepResearchModel(llm, fallback=RuleBasedDeepResearchModel())

    return DeepResearchToolExecutor(
        enabled=enabled,
        atomic_search=provider,
        research_model=research_model,
    )
