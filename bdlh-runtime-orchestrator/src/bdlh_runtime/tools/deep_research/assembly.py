"""确定性装配 ResearchBundle（BDLH 收口，非官方 final_report）。"""

from __future__ import annotations

from bdlh_runtime.tools.deep_research.contracts import (
    DeepResearchRequest,
    ResearchBundle,
    ResearchFinding,
    ResearchSource,
    ResearchUsage,
)


def assemble_research_bundle(
    request: DeepResearchRequest,
    *,
    research_brief: str = "",
    findings: list[ResearchFinding] | None = None,
    sources: list[ResearchSource] | None = None,
    conflicts: list[str] | None = None,
    limitations: list[str] | None = None,
    research_summary: str = "",
    clarification_questions: list[str] | None = None,
    missing_fields: list[str] | None = None,
    usage: ResearchUsage | None = None,
    deep_trigger_reasons: list[str] | None = None,
    budget_exhausted: bool = False,
    provider_failed: bool = False,
) -> ResearchBundle:
    """按来源闭合与可计算覆盖裁定状态；模型 Complete 不得单独决定 COMPLETE。"""

    findings = list(findings or [])
    sources = list(sources or [])
    conflicts = list(conflicts or [])
    limitations = list(limitations or [])
    clarification_questions = list(clarification_questions or [])
    missing_fields = list(missing_fields or [])
    usage = usage or ResearchUsage()
    if budget_exhausted:
        usage = usage.model_copy(update={"budget_exhausted": True})

    source_ids = {s.source_id for s in sources}
    closed_findings: list[ResearchFinding] = []
    for finding in findings:
        bound = [sid for sid in finding.source_ids if sid in source_ids]
        if not bound:
            limitations.append(f"finding_without_source:{finding.finding_id}")
            continue
        closed_findings.append(finding.model_copy(update={"source_ids": bound}))

    if missing_fields or clarification_questions:
        return ResearchBundle(
            request_id=request.request_id,
            question=request.question,
            research_brief=research_brief,
            status="NEEDS_CLARIFICATION",
            findings=closed_findings,
            sources=sources,
            conflicts=conflicts,
            limitations=limitations,
            research_summary=research_summary,
            clarification_questions=clarification_questions,
            missing_fields=missing_fields,
            usage=usage,
            deep_trigger_reasons=list(deep_trigger_reasons or []),
        )

    topics = [t.strip() for t in request.research_topics if t.strip()]
    criteria = [c.strip() for c in request.success_criteria if c.strip()]
    coverage_computable = bool(topics or criteria)

    if provider_failed and not sources:
        return ResearchBundle(
            request_id=request.request_id,
            question=request.question,
            research_brief=research_brief,
            status="FAILED",
            findings=[],
            sources=[],
            conflicts=conflicts,
            limitations=limitations + ["ATOMIC_SEARCH_UNAVAILABLE"],
            research_summary=research_summary,
            usage=usage,
            deep_trigger_reasons=list(deep_trigger_reasons or []),
        )

    if not sources or not closed_findings:
        status = "LIMITED" if budget_exhausted or provider_failed else "FAILED"
        if not sources:
            limitations = limitations + ["no_valid_sources"]
        return ResearchBundle(
            request_id=request.request_id,
            question=request.question,
            research_brief=research_brief,
            status=status,
            findings=closed_findings,
            sources=sources,
            conflicts=conflicts,
            limitations=limitations,
            research_summary=research_summary,
            usage=usage,
            deep_trigger_reasons=list(deep_trigger_reasons or []),
        )

    if budget_exhausted or provider_failed or conflicts or not coverage_computable:
        return ResearchBundle(
            request_id=request.request_id,
            question=request.question,
            research_brief=research_brief,
            status="PARTIAL",
            findings=closed_findings,
            sources=sources,
            conflicts=conflicts,
            limitations=limitations + ([] if coverage_computable else ["coverage_not_computable"]),
            research_summary=research_summary,
            usage=usage,
            deep_trigger_reasons=list(deep_trigger_reasons or []),
        )

    return ResearchBundle(
        request_id=request.request_id,
        question=request.question,
        research_brief=research_brief,
        status="COMPLETE",
        findings=closed_findings,
        sources=sources,
        conflicts=conflicts,
        limitations=limitations,
        research_summary=research_summary,
        usage=usage,
        deep_trigger_reasons=list(deep_trigger_reasons or []),
    )
