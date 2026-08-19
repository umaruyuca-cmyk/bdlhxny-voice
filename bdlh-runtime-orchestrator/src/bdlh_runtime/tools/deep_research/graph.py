"""Deep Research 内部 LangGraph 子图（ADR-016 §6.2 / 00 Prompt §6.5.3）。

节点：
  write_research_brief → research_supervisor(plan)
  → researcher_round（条件循环）→ compress_research → assemble_research_bundle

仅 Tool 进程内使用；不注册为公开 Capability Graph，不经 Gateway 回调 web_search。
"""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Literal
from urllib.parse import urlparse

from langgraph.graph import END, START, StateGraph

from bdlh_runtime.tools.deep_research.assembly import assemble_research_bundle
from bdlh_runtime.tools.deep_research.atomic_search import AtomicSearchPort, AtomicSearchRequest
from bdlh_runtime.tools.deep_research.contracts import (
    DeepResearchRequest,
    ResearchFinding,
    ResearchSource,
    ResearchUsage,
)
from bdlh_runtime.tools.deep_research.graph_state import DeepResearchGraphState
from bdlh_runtime.tools.deep_research.models import (
    DeepResearchModel,
    RuleBasedDeepResearchModel,
)


def build_deep_research_graph(
    *,
    atomic_search: AtomicSearchPort,
    research_model: DeepResearchModel | None = None,
):
    """编译隔离 Deep Research 子图。"""

    model = research_model or RuleBasedDeepResearchModel()

    async def write_research_brief(state: DeepResearchGraphState) -> dict[str, Any]:
        request = DeepResearchRequest.model_validate(state["request"])
        brief = await model.write_brief(request)
        limitations = list(state.get("limitations") or [])
        if isinstance(model, RuleBasedDeepResearchModel):
            if "rule_based_orchestration" not in limitations:
                limitations.append("rule_based_orchestration")
        return {
            "brief": brief,
            "model_calls": int(state.get("model_calls") or 0) + 1,
            "limitations": limitations,
            "phase": "brief",
        }

    async def research_supervisor(state: DeepResearchGraphState) -> dict[str, Any]:
        request = DeepResearchRequest.model_validate(state["request"])
        brief = state.get("brief") or ""
        plans = await model.plan_units(request, brief=brief)
        if not plans:
            plans = await RuleBasedDeepResearchModel().plan_units(request, brief=brief)
        units = [
            {
                "topic": plan.topic,
                "query": plan.query,
                "urls_seen": [],
                "stagnant_rounds": 0,
                "react_calls": 0,
                "snippets": [],
                "source_ids": [],
                "done": False,
            }
            for plan in plans
        ]
        return {
            "units": units,
            "model_calls": int(state.get("model_calls") or 0) + 1,
            "supervisor_round": 0,
            "phase": "supervisor",
        }

    async def researcher_round(state: DeepResearchGraphState) -> dict[str, Any]:
        request = DeepResearchRequest.model_validate(state["request"])
        budget = request.budget
        units = [dict(u) for u in (state.get("units") or [])]
        sources = list(state.get("sources") or [])
        findings = list(state.get("findings") or [])
        limitations = list(state.get("limitations") or [])
        search_calls = int(state.get("search_calls") or 0)
        model_calls = int(state.get("model_calls") or 0)
        source_counter = int(state.get("source_counter") or 0)
        supervisor_round = int(state.get("supervisor_round") or 0)
        provider_failed = bool(state.get("provider_failed"))
        budget_exhausted = bool(state.get("budget_exhausted"))
        started = float(state.get("started_perf") or perf_counter())
        now = datetime.now(timezone.utc).isoformat()
        progressed = False

        if (perf_counter() - started) >= budget.runtime_seconds:
            budget_exhausted = True
            if "runtime_seconds_exhausted" not in limitations:
                limitations.append("runtime_seconds_exhausted")
            return {
                "limitations": limitations,
                "budget_exhausted": True,
                "phase": "researcher",
                "supervisor_round": supervisor_round + 1,
            }

        if search_calls >= budget.search_call_limit:
            budget_exhausted = True
            if "search_call_limit_exhausted" not in limitations:
                limitations.append("search_call_limit_exhausted")
            return {
                "limitations": limitations,
                "budget_exhausted": True,
                "phase": "researcher",
                "supervisor_round": supervisor_round + 1,
            }

        for unit in units:
            if unit.get("done"):
                continue
            if search_calls >= budget.search_call_limit:
                budget_exhausted = True
                if "search_call_limit_exhausted" not in limitations:
                    limitations.append("search_call_limit_exhausted")
                break
            if (perf_counter() - started) >= budget.runtime_seconds:
                budget_exhausted = True
                if "runtime_seconds_exhausted" not in limitations:
                    limitations.append("runtime_seconds_exhausted")
                break

            urls_seen = set(unit.get("urls_seen") or [])
            turn = await model.next_researcher_turn(
                request,
                unit_topic=str(unit["topic"]),
                last_query=str(unit["query"]),
                hit_count=len(urls_seen),
                stagnant_rounds=int(unit.get("stagnant_rounds") or 0),
                no_new_url_limit=budget.no_new_url_rounds_limit,
                react_calls_used=int(unit.get("react_calls") or 0),
                max_react_tool_calls=budget.max_react_tool_calls,
            )
            model_calls += 1
            if not turn.next_query:
                unit["done"] = True
                continue

            unit["query"] = turn.next_query
            batch = await atomic_search.search(
                AtomicSearchRequest(
                    request_id=(
                        f"{request.request_id}:{unit['topic']}:{supervisor_round}"
                    ),
                    queries=[str(unit["query"])],
                    include_domains=list(request.include_domains),
                    exclude_domains=list(request.exclude_domains),
                    max_results=min(5, budget.search_call_limit - search_calls),
                )
            )
            search_calls += 1
            unit["react_calls"] = int(unit.get("react_calls") or 0) + 1

            if batch.status == "UNAVAILABLE":
                provider_failed = True
                code = batch.error_code or "ATOMIC_SEARCH_UNAVAILABLE"
                if code not in limitations:
                    limitations.append(code)
                unit["stagnant_rounds"] = int(unit.get("stagnant_rounds") or 0) + 1
                continue

            new_urls = 0
            for hit in batch.hits:
                if hit.url in urls_seen:
                    continue
                urls_seen.add(hit.url)
                new_urls += 1
                source_counter += 1
                source_id = f"src-{source_counter}"
                domain = hit.domain or (urlparse(hit.url).netloc if hit.url else "")
                sources.append(
                    ResearchSource(
                        source_id=source_id,
                        title=hit.title,
                        url=hit.url,
                        domain=domain,
                        published_at=hit.published_at,
                        retrieved_at=hit.retrieved_at or now,
                        summary=hit.summary,
                        source_type="web",
                    ).model_dump()
                )
                snippet = hit.summary or hit.title
                unit.setdefault("snippets", []).append(snippet)
                unit.setdefault("source_ids", []).append(source_id)
                findings.append(
                    ResearchFinding(
                        finding_id=f"f-{source_counter}",
                        statement=snippet,
                        source_ids=[source_id],
                        confidence="MEDIUM",
                    ).model_dump()
                )

            unit["urls_seen"] = sorted(urls_seen)
            if new_urls == 0:
                unit["stagnant_rounds"] = int(unit.get("stagnant_rounds") or 0) + 1
            else:
                unit["stagnant_rounds"] = 0
                progressed = True

            if (
                int(unit["stagnant_rounds"]) >= budget.no_new_url_rounds_limit
                or int(unit["react_calls"]) >= budget.max_react_tool_calls
            ):
                unit["done"] = True

        if not progressed and all(bool(u.get("done")) for u in units):
            if "no_new_url_hard_stop" not in limitations:
                limitations.append("no_new_url_hard_stop")

        return {
            "units": units,
            "sources": sources,
            "findings": findings,
            "limitations": limitations,
            "search_calls": search_calls,
            "model_calls": model_calls,
            "source_counter": source_counter,
            "supervisor_round": supervisor_round + 1,
            "provider_failed": provider_failed,
            "budget_exhausted": budget_exhausted,
            "phase": "researcher",
        }

    def route_after_researcher(
        state: DeepResearchGraphState,
    ) -> Literal["researcher_round", "compress_research"]:
        request = DeepResearchRequest.model_validate(state["request"])
        budget = request.budget
        if state.get("budget_exhausted"):
            return "compress_research"
        if int(state.get("supervisor_round") or 0) >= budget.max_supervisor_iterations:
            return "compress_research"
        if int(state.get("search_calls") or 0) >= budget.search_call_limit:
            return "compress_research"
        units = state.get("units") or []
        if units and all(bool(u.get("done")) for u in units):
            return "compress_research"
        started = float(state.get("started_perf") or perf_counter())
        if (perf_counter() - started) >= budget.runtime_seconds:
            return "compress_research"
        return "researcher_round"

    async def compress_research(state: DeepResearchGraphState) -> dict[str, Any]:
        request = DeepResearchRequest.model_validate(state["request"])
        summaries: list[str] = []
        model_calls = int(state.get("model_calls") or 0)
        for unit in state.get("units") or []:
            notes = await model.compress_unit(
                request,
                unit_topic=str(unit.get("topic") or ""),
                snippets=list(unit.get("snippets") or []),
            )
            model_calls += 1
            summaries.append(notes.summary)
        return {
            "unit_summaries": summaries,
            "model_calls": model_calls,
            "phase": "compress",
        }

    async def assemble_node(state: DeepResearchGraphState) -> dict[str, Any]:
        request = DeepResearchRequest.model_validate(state["request"])
        started = float(state.get("started_perf") or perf_counter())
        duration_ms = int((perf_counter() - started) * 1000)
        brief = state.get("brief") or ""
        unit_summaries = list(state.get("unit_summaries") or [])
        usage = ResearchUsage(
            model_calls=int(state.get("model_calls") or 0),
            search_calls=int(state.get("search_calls") or 0),
            research_units=len(state.get("units") or []),
            duration_ms=duration_ms,
            budget_exhausted=bool(state.get("budget_exhausted")),
        )
        findings = [
            ResearchFinding.model_validate(item) for item in (state.get("findings") or [])
        ]
        sources = [
            ResearchSource.model_validate(item) for item in (state.get("sources") or [])
        ]
        bundle = assemble_research_bundle(
            request,
            research_brief=brief,
            findings=findings,
            sources=sources,
            research_summary="\n".join(s for s in unit_summaries if s) or brief,
            usage=usage,
            limitations=list(state.get("limitations") or []),
            deep_trigger_reasons=list(state.get("deep_trigger_reasons") or []),
            budget_exhausted=bool(state.get("budget_exhausted")),
            provider_failed=bool(state.get("provider_failed")),
        )
        if not state.get("allow_complete") and bundle.status == "COMPLETE":
            bundle = bundle.model_copy(
                update={
                    "status": "PARTIAL",
                    "limitations": list(bundle.limitations)
                    + ["complete_gated_until_llm_eval"],
                }
            )
        return {"bundle": bundle.model_dump(), "phase": "assembled"}

    graph = StateGraph(DeepResearchGraphState)
    graph.add_node("write_research_brief", write_research_brief)
    graph.add_node("research_supervisor", research_supervisor)
    graph.add_node("researcher_round", researcher_round)
    graph.add_node("compress_research", compress_research)
    graph.add_node("assemble_research_bundle", assemble_node)

    graph.add_edge(START, "write_research_brief")
    graph.add_edge("write_research_brief", "research_supervisor")
    graph.add_edge("research_supervisor", "researcher_round")
    graph.add_conditional_edges(
        "researcher_round",
        route_after_researcher,
        {
            "researcher_round": "researcher_round",
            "compress_research": "compress_research",
        },
    )
    graph.add_edge("compress_research", "assemble_research_bundle")
    graph.add_edge("assemble_research_bundle", END)
    return graph.compile()
