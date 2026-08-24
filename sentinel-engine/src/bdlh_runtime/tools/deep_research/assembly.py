"""确定性装配 ResearchBundle（BDLH 收口，非官方 final_report）。"""

from __future__ import annotations

import re

from bdlh_runtime.tools.deep_research.contracts import (
    DeepResearchRequest,
    ResearchBundle,
    ResearchFinding,
    ResearchSource,
    ResearchUsage,
)

_TOKEN_SPLIT = re.compile(r"[\s,，。；;：:、/\\|]+")


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
    criteria_covered = _success_criteria_covered(criteria, closed_findings) if criteria else True
    # 有 success_criteria 时以准则覆盖为准；仅有 topics 时要求弱覆盖
    topics_covered = True if criteria else _topics_covered(topics, closed_findings, research_summary)

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
        if budget_exhausted:
            limitations = limitations + ["DEEP_RESEARCH_BUDGET_EXHAUSTED"]
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

    # 禁止假 COMPLETE：预算耗尽、冲突、覆盖不可算、准则/主题未覆盖 → PARTIAL/LIMITED
    if budget_exhausted:
        return ResearchBundle(
            request_id=request.request_id,
            question=request.question,
            research_brief=research_brief,
            status="LIMITED",
            findings=closed_findings,
            sources=sources,
            conflicts=conflicts,
            limitations=limitations + ["DEEP_RESEARCH_BUDGET_EXHAUSTED"],
            research_summary=research_summary,
            usage=usage,
            deep_trigger_reasons=list(deep_trigger_reasons or []),
        )

    if provider_failed or conflicts or not coverage_computable or not criteria_covered or not topics_covered:
        gap_notes: list[str] = []
        if not coverage_computable:
            gap_notes.append("coverage_not_computable")
        if criteria and not criteria_covered:
            gap_notes.append("success_criteria_uncovered")
        if topics and not topics_covered:
            gap_notes.append("research_topics_uncovered")
        return ResearchBundle(
            request_id=request.request_id,
            question=request.question,
            research_brief=research_brief,
            status="PARTIAL",
            findings=closed_findings,
            sources=sources,
            conflicts=conflicts,
            limitations=limitations + gap_notes,
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


def _success_criteria_covered(criteria: list[str], findings: list[ResearchFinding]) -> bool:
    """关键准则须被至少一条 finding 的语句弱覆盖（禁止无引用式假 COMPLETE）。"""
    if not criteria:
        return True
    corpus = " ".join(item.statement for item in findings).lower()
    for criterion in criteria:
        tokens = [tok for tok in _tokenize(criterion) if len(tok) >= 2]
        if not tokens:
            continue
        if not any(tok in corpus for tok in tokens):
            return False
    return True


def _topics_covered(topics: list[str], findings: list[ResearchFinding], summary: str) -> bool:
    if not topics:
        return True
    corpus = (" ".join(item.statement for item in findings) + " " + (summary or "")).lower()
    for topic in topics:
        tokens = [tok for tok in _tokenize(topic) if len(tok) >= 2]
        if tokens and not any(tok in corpus for tok in tokens):
            return False
    return True


def _tokenize(text: str) -> list[str]:
    parts = _TOKEN_SPLIT.split((text or "").lower())
    return [p for p in parts if p]
