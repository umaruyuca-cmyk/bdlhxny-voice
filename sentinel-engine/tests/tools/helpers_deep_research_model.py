"""Tests-only rule-based Deep Research model — not a product path."""

from __future__ import annotations

from bdlh_runtime.tools.deep_research.contracts import DeepResearchRequest
from bdlh_runtime.tools.deep_research.models import (
    CompressedUnitNotes,
    ResearcherTurn,
    ResearchUnitPlan,
)


class RuleBasedDeepResearchModel:
    """确定性规则模型：隔离测试 / 评测 harness 用。"""

    async def write_brief(self, request: DeepResearchRequest) -> str:
        return (
            f"Objective: {request.objective}\n"
            f"Question: {request.question}\n"
            f"Topics: {', '.join(request.research_topics) or '(none)'}\n"
            f"Criteria: {', '.join(request.success_criteria) or '(none)'}"
        )

    async def plan_units(self, request: DeepResearchRequest, *, brief: str) -> list[ResearchUnitPlan]:
        del brief
        limit = request.budget.max_concurrent_research_units
        topics = [t.strip() for t in request.research_topics if t.strip()]
        if topics:
            return [ResearchUnitPlan(topic=topic, query=f"{request.question} — {topic}") for topic in topics[:limit]]
        criteria = [c.strip() for c in request.success_criteria if c.strip()]
        if len(criteria) >= 2:
            return [
                ResearchUnitPlan(
                    topic=f"criterion:{index + 1}",
                    query=f"{request.question} — {item}",
                )
                for index, item in enumerate(criteria[:limit])
            ]
        return [ResearchUnitPlan(topic="primary", query=request.question)]

    async def next_researcher_turn(
        self,
        request: DeepResearchRequest,
        *,
        unit_topic: str,
        last_query: str,
        hit_count: int,
        stagnant_rounds: int,
        no_new_url_limit: int,
        react_calls_used: int,
        max_react_tool_calls: int,
    ) -> ResearcherTurn:
        del request, unit_topic
        if react_calls_used >= max_react_tool_calls:
            return ResearcherTurn(next_query=None, reason="max_react_tool_calls")
        if stagnant_rounds >= no_new_url_limit:
            return ResearcherTurn(next_query=None, reason="no_new_url_hard_stop")
        if hit_count >= 3 and stagnant_rounds >= 1:
            return ResearcherTurn(next_query=None, reason="enough_hits")
        if react_calls_used == 0:
            return ResearcherTurn(next_query=last_query, reason="initial_search")
        refined = f"{last_query} 补充来源"
        return ResearcherTurn(next_query=refined, reason="gap_followup")

    async def compress_unit(
        self,
        request: DeepResearchRequest,
        *,
        unit_topic: str,
        snippets: list[str],
    ) -> CompressedUnitNotes:
        del request
        statements = tuple(s.strip() for s in snippets if s and s.strip())[:8]
        summary = f"[{unit_topic}] " + " | ".join(statements[:3]) if statements else f"[{unit_topic}] no snippets"
        return CompressedUnitNotes(summary=summary, finding_statements=statements)
