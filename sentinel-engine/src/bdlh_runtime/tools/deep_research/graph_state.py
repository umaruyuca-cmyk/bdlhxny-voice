"""Deep Research 内部 LangGraph 状态（不对 Capability Gateway 暴露）。"""

from __future__ import annotations

from typing import Any, TypedDict


class DeepResearchGraphState(TypedDict, total=False):
    """子图状态；禁止放入 Secret / 完整网页 / 隐藏思维链。"""

    request: dict[str, Any]
    brief: str
    units: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    limitations: list[str]
    unit_summaries: list[str]
    deep_trigger_reasons: list[str]
    search_calls: int
    model_calls: int
    source_counter: int
    supervisor_round: int
    provider_failed: bool
    budget_exhausted: bool
    started_perf: float
    allow_complete: bool
    phase: str
    bundle: dict[str, Any] | None
