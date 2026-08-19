"""Deep Research 内部模型角色（假 LLM / 规则 / 可选 LangChain）。

Supervisor / Researcher 的「继续还是结束」仅为建议；最终状态由 assembly 裁定。
无 LLM 时用 ``RuleBasedDeepResearchModel``，保证隔离测试可确定性跑通。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from bdlh_runtime.tools.deep_research.contracts import DeepResearchRequest

logger = logging.getLogger("bdlh_runtime.tools.deep_research.models")


@dataclass(frozen=True)
class ResearchUnitPlan:
    topic: str
    query: str


@dataclass(frozen=True)
class ResearcherTurn:
    """Researcher 一轮决策：None query 表示结束本单元并进入压缩。"""

    next_query: str | None
    reason: str = ""


@dataclass(frozen=True)
class CompressedUnitNotes:
    summary: str
    finding_statements: tuple[str, ...] = ()


class DeepResearchModel(Protocol):
    async def write_brief(self, request: DeepResearchRequest) -> str: ...

    async def plan_units(
        self, request: DeepResearchRequest, *, brief: str
    ) -> list[ResearchUnitPlan]: ...

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
    ) -> ResearcherTurn: ...

    async def compress_unit(
        self,
        request: DeepResearchRequest,
        *,
        unit_topic: str,
        snippets: list[str],
    ) -> CompressedUnitNotes: ...


class RuleBasedDeepResearchModel:
    """确定性规则模型：无 LLM / 假 LLM 路径的默认实现。"""

    async def write_brief(self, request: DeepResearchRequest) -> str:
        return (
            f"Objective: {request.objective}\n"
            f"Question: {request.question}\n"
            f"Topics: {', '.join(request.research_topics) or '(none)'}\n"
            f"Criteria: {', '.join(request.success_criteria) or '(none)'}"
        )

    async def plan_units(
        self, request: DeepResearchRequest, *, brief: str
    ) -> list[ResearchUnitPlan]:
        del brief  # 规则路径不依赖 brief 文本
        limit = request.budget.max_concurrent_research_units
        topics = [t.strip() for t in request.research_topics if t.strip()]
        if topics:
            return [
                ResearchUnitPlan(topic=topic, query=f"{request.question} — {topic}")
                for topic in topics[:limit]
            ]
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
        # 轻微改写以体现补搜意图（确定性）
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
        summary = (
            f"[{unit_topic}] " + " | ".join(statements[:3])
            if statements
            else f"[{unit_topic}] no snippets"
        )
        return CompressedUnitNotes(summary=summary, finding_statements=statements)


class LangchainDeepResearchModel:
    """可选 DeepSeek/Chat 模型槽位；结构化失败时回落规则模型。"""

    def __init__(self, llm: Any, *, fallback: DeepResearchModel | None = None) -> None:
        self._llm = llm
        self._fallback = fallback or RuleBasedDeepResearchModel()

    async def write_brief(self, request: DeepResearchRequest) -> str:
        prompt = (
            "将以下研究任务压缩为一段英文或中文 research brief（<=400字），"
            "包含目标、范围、成功条件，不要编造事实。\n"
            f"question={request.question}\n"
            f"objective={request.objective}\n"
            f"topics={request.research_topics}\n"
            f"criteria={request.success_criteria}\n"
        )
        text = await self._ainvoke_text(prompt)
        if text:
            return text.strip()
        return await self._fallback.write_brief(request)

    async def plan_units(
        self, request: DeepResearchRequest, *, brief: str
    ) -> list[ResearchUnitPlan]:
        limit = request.budget.max_concurrent_research_units
        prompt = (
            "根据 brief 拆出研究单元。只输出 JSON 数组，元素含 topic,query 字段，"
            f"最多 {limit} 个，不要其它文字。\nbrief=\n{brief}\n"
            f"question={request.question}\n"
        )
        text = await self._ainvoke_text(prompt)
        units = _parse_unit_plans(text, limit=limit)
        if units:
            return units
        return await self._fallback.plan_units(request, brief=brief)

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
        # 硬停优先于模型建议（预算真源）
        if react_calls_used >= max_react_tool_calls or stagnant_rounds >= no_new_url_limit:
            return await self._fallback.next_researcher_turn(
                request,
                unit_topic=unit_topic,
                last_query=last_query,
                hit_count=hit_count,
                stagnant_rounds=stagnant_rounds,
                no_new_url_limit=no_new_url_limit,
                react_calls_used=react_calls_used,
                max_react_tool_calls=max_react_tool_calls,
            )
        prompt = (
            "Decide next web search for one research unit. "
            'Return JSON {"next_query": string|null, "reason": string}. '
            "null next_query means stop this unit.\n"
            f"topic={unit_topic} hits={hit_count} stagnant={stagnant_rounds} "
            f"react_used={react_calls_used} last_query={last_query}\n"
            f"question={request.question}\n"
        )
        text = await self._ainvoke_text(prompt)
        parsed = _parse_researcher_turn(text)
        if parsed is not None:
            return parsed
        return await self._fallback.next_researcher_turn(
            request,
            unit_topic=unit_topic,
            last_query=last_query,
            hit_count=hit_count,
            stagnant_rounds=stagnant_rounds,
            no_new_url_limit=no_new_url_limit,
            react_calls_used=react_calls_used,
            max_react_tool_calls=max_react_tool_calls,
        )

    async def compress_unit(
        self,
        request: DeepResearchRequest,
        *,
        unit_topic: str,
        snippets: list[str],
    ) -> CompressedUnitNotes:
        prompt = (
            "压缩研究摘录为简短 summary 与 findings 列表。"
            '只输出 JSON {"summary":"...","findings":["..."]}。\n'
            f"topic={unit_topic}\nsnippets={snippets[:12]}\n"
            f"question={request.question}\n"
        )
        text = await self._ainvoke_text(prompt)
        notes = _parse_compress(text)
        if notes is not None:
            return notes
        return await self._fallback.compress_unit(
            request, unit_topic=unit_topic, snippets=snippets
        )

    async def _ainvoke_text(self, prompt: str) -> str | None:
        try:
            result = await self._llm.ainvoke(prompt)
            content = getattr(result, "content", result)
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, dict) and "text" in item:
                        parts.append(str(item["text"]))
                    else:
                        parts.append(str(getattr(item, "text", item)))
                return "\n".join(parts)
            return str(content) if content is not None else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("deep_research_llm_failed err=%s", type(exc).__name__)
            return None


def _parse_unit_plans(text: str | None, *, limit: int) -> list[ResearchUnitPlan]:
    data = _extract_json(text)
    if not isinstance(data, list):
        return []
    units: list[ResearchUnitPlan] = []
    for item in data[:limit]:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or "").strip()
        query = str(item.get("query") or "").strip()
        if topic and query:
            units.append(ResearchUnitPlan(topic=topic, query=query))
    return units


def _parse_researcher_turn(text: str | None) -> ResearcherTurn | None:
    data = _extract_json(text)
    if not isinstance(data, dict) or "next_query" not in data:
        return None
    raw = data.get("next_query")
    next_query = None if raw is None else str(raw).strip() or None
    return ResearcherTurn(next_query=next_query, reason=str(data.get("reason") or "llm"))


def _parse_compress(text: str | None) -> CompressedUnitNotes | None:
    data = _extract_json(text)
    if not isinstance(data, dict):
        return None
    summary = str(data.get("summary") or "").strip()
    findings = data.get("findings") or data.get("finding_statements") or []
    if not isinstance(findings, list):
        findings = []
    statements = tuple(str(x).strip() for x in findings if str(x).strip())
    if not summary and not statements:
        return None
    return CompressedUnitNotes(summary=summary or "compressed", finding_statements=statements)


def _extract_json(text: str | None) -> Any | None:
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start_obj = text.find("{")
    start_arr = text.find("[")
    starts = [i for i in (start_obj, start_arr) if i >= 0]
    if not starts:
        return None
    start = min(starts)
    snippet = text[start:]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        # 截到最后一个 } 或 ]
        end = max(snippet.rfind("}"), snippet.rfind("]"))
        if end < 0:
            return None
        try:
            return json.loads(snippet[: end + 1])
        except json.JSONDecodeError:
            return None
