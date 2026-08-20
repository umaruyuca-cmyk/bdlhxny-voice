"""固定复合 Deep Research Tool（ADR-016 APPROVED 开发阶段 / 00 Prompt §6.5）。

契约、调用策略、私有原子搜索口与 Supervisor/Researcher 编排；**默认 Feature Flag 关闭**，
不得改变 ``research.web_search`` 生产语义，不得经 Adapter 静默升档。
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
from bdlh_runtime.tools.deep_research.bailian_provider import (
    DEFAULT_BAILIAN_WEB_SEARCH_ENDPOINT,
    BailianWebSearchProvider,
    parse_bailian_search_payload,
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
from bdlh_runtime.tools.deep_research.graph import build_deep_research_graph
from bdlh_runtime.tools.deep_research.models import (
    LangchainDeepResearchModel,
    RuleBasedDeepResearchModel,
)
from bdlh_runtime.tools.deep_research.orchestration import run_deep_research

__all__ = [
    "DEEP_SEARCH_CAPABILITY",
    "DEFAULT_BAILIAN_WEB_SEARCH_ENDPOINT",
    "WEB_SEARCH_CAPABILITY",
    "AtomicSearchBatch",
    "AtomicSearchHit",
    "AtomicSearchPort",
    "AtomicSearchRequest",
    "BailianWebSearchProvider",
    "DeepResearchBudget",
    "DeepResearchRequest",
    "DeepResearchToolExecutor",
    "DeepTriggerDecision",
    "FakeAtomicSearchPort",
    "LangchainDeepResearchModel",
    "ResearchBundle",
    "ResearchFinding",
    "ResearchSource",
    "RuleBasedDeepResearchModel",
    "assemble_research_bundle",
    "build_deep_research_graph",
    "evaluate_deep_research_trigger",
    "parse_bailian_search_payload",
    "run_deep_research",
]
