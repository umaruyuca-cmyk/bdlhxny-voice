"""固定复合 Deep Research Tool（ADR-016 / 00 Prompt §6.5）。

ADR 仍为 PROPOSED 时：本包提供契约、调用策略、私有原子搜索口与隔离执行骨架；
**默认关闭**，不得改变 ``research.web_search`` 生产语义，不得经 Adapter 静默升档。
"""

from __future__ import annotations

from bdlh_runtime.tools.deep_research.assembly import assemble_research_bundle
from bdlh_runtime.tools.deep_research.atomic_search import (
    AtomicSearchBatch,
    AtomicSearchHit,
    AtomicSearchPort,
    AtomicSearchRequest,
    FakeAtomicSearchPort,
)
from bdlh_runtime.tools.deep_research.call_policy import (
    DeepTriggerDecision,
    evaluate_deep_research_trigger,
)
from bdlh_runtime.tools.deep_research.contracts import (
    DEEP_SEARCH_CAPABILITY,
    WEB_SEARCH_CAPABILITY,
    DeepResearchBudget,
    DeepResearchRequest,
    ResearchBundle,
    ResearchFinding,
    ResearchSource,
)
from bdlh_runtime.tools.deep_research.executor import DeepResearchToolExecutor

__all__ = [
    "DEEP_SEARCH_CAPABILITY",
    "WEB_SEARCH_CAPABILITY",
    "AtomicSearchBatch",
    "AtomicSearchHit",
    "AtomicSearchPort",
    "AtomicSearchRequest",
    "DeepResearchBudget",
    "DeepResearchRequest",
    "DeepResearchToolExecutor",
    "DeepTriggerDecision",
    "FakeAtomicSearchPort",
    "ResearchBundle",
    "ResearchFinding",
    "ResearchSource",
    "assemble_research_bundle",
    "evaluate_deep_research_trigger",
]
