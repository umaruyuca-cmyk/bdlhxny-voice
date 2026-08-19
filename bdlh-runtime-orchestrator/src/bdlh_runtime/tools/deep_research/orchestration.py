"""Deep Research 编排入口（ADR-016 §6 / §17）。

对外稳定 API：``run_deep_research``。内部委托 LangGraph 子图
（brief → supervisor → researcher 循环 → compress → assemble）。
"""

from __future__ import annotations

from time import perf_counter

from bdlh_runtime.tools.deep_research.atomic_search import AtomicSearchPort
from bdlh_runtime.tools.deep_research.contracts import DeepResearchRequest, ResearchBundle
from bdlh_runtime.tools.deep_research.graph import build_deep_research_graph
from bdlh_runtime.tools.deep_research.models import (
    DeepResearchModel,
    RuleBasedDeepResearchModel,
)


async def run_deep_research(
    request: DeepResearchRequest,
    *,
    atomic_search: AtomicSearchPort,
    deep_trigger_reasons: list[str] | None = None,
    research_model: DeepResearchModel | None = None,
    allow_complete: bool = False,
) -> ResearchBundle:
    """执行隔离版 Deep 编排并返回 ResearchBundle。

    ``allow_complete``：仅当注入非规则 LLM 且评测确认后可由装配器标 COMPLETE；
    默认 False，规则骨架强制 PARTIAL。
    """

    model = research_model or RuleBasedDeepResearchModel()
    graph = build_deep_research_graph(
        atomic_search=atomic_search,
        research_model=model,
    )
    initial = {
        "request": request.model_dump(),
        "brief": "",
        "units": [],
        "sources": [],
        "findings": [],
        "limitations": [],
        "unit_summaries": [],
        "deep_trigger_reasons": list(deep_trigger_reasons or []),
        "search_calls": 0,
        "model_calls": 0,
        "source_counter": 0,
        "supervisor_round": 0,
        "provider_failed": False,
        "budget_exhausted": False,
        "started_perf": perf_counter(),
        "allow_complete": allow_complete,
        "phase": "start",
        "bundle": None,
    }
    final = await graph.ainvoke(initial)
    payload = final.get("bundle")
    if not payload:
        raise RuntimeError("deep research graph finished without ResearchBundle")
    return ResearchBundle.model_validate(payload)
