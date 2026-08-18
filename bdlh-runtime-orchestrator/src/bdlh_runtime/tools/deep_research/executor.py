"""DeepResearchToolExecutor：隔离骨架（ADR-016 PROPOSED）。

默认 ``enabled=False``：返回 UNAVAILABLE，不跑编排、不碰 SearXNG。
``enabled=True`` 且注入 ``AtomicSearchPort`` 时：仅做「简报占位 → 单次原子搜索 →
确定性装配」的最小可测路径，**不含**完整 Supervisor/Researcher 图（待 APPROVED 后切片）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4

from bdlh_runtime.contracts.observation import DataQuality, Observation, ProvenanceRecord
from bdlh_runtime.tools.deep_research.assembly import assemble_research_bundle
from bdlh_runtime.tools.deep_research.atomic_search import AtomicSearchPort, AtomicSearchRequest
from bdlh_runtime.tools.deep_research.contracts import (
    DEEP_SEARCH_CAPABILITY,
    DeepResearchRequest,
    ResearchFinding,
    ResearchSource,
    ResearchUsage,
)


class DeepResearchToolExecutor:
    """固定复合研究 Capability 执行器。"""

    def __init__(
        self,
        *,
        enabled: bool = False,
        atomic_search: AtomicSearchPort | None = None,
    ) -> None:
        self._enabled = enabled
        self._atomic_search = atomic_search

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def execute(self, capability: str, arguments: dict[str, Any]) -> Observation:
        if capability != DEEP_SEARCH_CAPABILITY:
            return self._observation(
                status="FAILED",
                error_code="DEEP_RESEARCH_INVALID_REQUEST",
                error_message=f"executor does not handle capability: {capability}",
                data=None,
            )

        if not self._enabled:
            return self._observation(
                status="UNAVAILABLE",
                error_code="DEEP_RESEARCH_NOT_ENABLED",
                error_message=(
                    "research.deep_search is feature-gated (ADR-016 PROPOSED); "
                    "use research.web_search for ordinary queries"
                ),
                data=None,
                known_unavailable=[DEEP_SEARCH_CAPABILITY],
            )

        try:
            request = DeepResearchRequest.model_validate(arguments)
        except Exception as exc:  # noqa: BLE001 — 契约错误统一映射
            return self._observation(
                status="FAILED",
                error_code="DEEP_RESEARCH_INVALID_REQUEST",
                error_message=str(exc),
                data=None,
            )

        missing: list[str] = []
        if not request.question.strip():
            missing.append("question")
        if not request.objective.strip():
            missing.append("objective")
        if missing:
            bundle = assemble_research_bundle(
                request,
                missing_fields=missing,
                clarification_questions=[f"请补充: {', '.join(missing)}"],
            )
            return self._bundle_observation(bundle, status="PARTIAL")

        if self._atomic_search is None:
            return self._observation(
                status="UNAVAILABLE",
                error_code="ATOMIC_SEARCH_UNAVAILABLE",
                error_message="AtomicSearchPort is not configured",
                data=None,
                known_unavailable=[DEEP_SEARCH_CAPABILITY],
            )

        started = perf_counter()
        brief = f"Research brief for: {request.question}"
        batch = await self._atomic_search.search(
            AtomicSearchRequest(
                request_id=request.request_id,
                queries=[request.question],
                include_domains=list(request.include_domains),
                exclude_domains=list(request.exclude_domains),
                max_results=min(5, request.budget.search_call_limit),
            )
        )
        duration_ms = int((perf_counter() - started) * 1000)
        usage = ResearchUsage(search_calls=1, research_units=1, duration_ms=duration_ms)

        if batch.status == "UNAVAILABLE":
            bundle = assemble_research_bundle(
                request,
                research_brief=brief,
                usage=usage,
                provider_failed=True,
                limitations=[batch.error_code or "ATOMIC_SEARCH_UNAVAILABLE"],
            )
            return self._bundle_observation(bundle, status="UNAVAILABLE")

        now = datetime.now(timezone.utc).isoformat()
        sources: list[ResearchSource] = []
        findings: list[ResearchFinding] = []
        for index, hit in enumerate(batch.hits):
            source_id = f"src-{index + 1}"
            sources.append(
                ResearchSource(
                    source_id=source_id,
                    title=hit.title,
                    url=hit.url,
                    domain=hit.domain,
                    published_at=hit.published_at,
                    retrieved_at=hit.retrieved_at or now,
                    summary=hit.summary,
                    source_type="web",
                )
            )
            findings.append(
                ResearchFinding(
                    finding_id=f"f-{index + 1}",
                    statement=hit.summary or hit.title,
                    source_ids=[source_id],
                    confidence="MEDIUM",
                )
            )

        bundle = assemble_research_bundle(
            request,
            research_brief=brief,
            findings=findings,
            sources=sources,
            research_summary=brief,
            usage=usage,
            provider_failed=batch.status == "EMPTY",
            limitations=["isolation_stub_no_supervisor"],
        )
        # 隔离骨架故意不标 COMPLETE（无完整 Supervisor）；有来源则为 PARTIAL
        if bundle.status == "COMPLETE":
            bundle = bundle.model_copy(
                update={
                    "status": "PARTIAL",
                    "limitations": list(bundle.limitations) + ["isolation_stub_no_supervisor"],
                }
            )
        obs_status = "SUCCESS" if bundle.status in {"PARTIAL", "COMPLETE"} else "FAILED"
        if bundle.status in {"LIMITED", "NEEDS_CLARIFICATION"}:
            obs_status = "PARTIAL"
        if bundle.status == "FAILED" and "ATOMIC_SEARCH_UNAVAILABLE" in bundle.limitations:
            obs_status = "UNAVAILABLE"
        return self._bundle_observation(bundle, status=obs_status)

    def _bundle_observation(self, bundle: Any, *, status: str) -> Observation:
        completeness = 1.0 if bundle.status == "COMPLETE" else 0.5 if bundle.sources else 0.0
        return Observation(
            observation_id=str(uuid4()),
            capability=DEEP_SEARCH_CAPABILITY,
            status=status,  # type: ignore[arg-type]
            data=bundle.model_dump(),
            data_quality=DataQuality(
                completeness=completeness,
                freshness="LIVE",
                quality_status="PARTIAL" if status == "PARTIAL" else ("OK" if status == "SUCCESS" else "INVALID"),
                known_unavailable=[],
            ),
            provenance=[
                ProvenanceRecord(
                    source="deep-research-executor",
                    tool=DEEP_SEARCH_CAPABILITY,
                    request_id=bundle.request_id,
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                )
            ],
            error_code=None if status in {"SUCCESS", "PARTIAL"} else "DEEP_RESEARCH_ASSEMBLY_FAILED",
            error_message=None if status in {"SUCCESS", "PARTIAL"} else bundle.status,
        )

    def _observation(
        self,
        *,
        status: str,
        error_code: str,
        error_message: str,
        data: Any,
        known_unavailable: list[str] | None = None,
    ) -> Observation:
        return Observation(
            observation_id=str(uuid4()),
            capability=DEEP_SEARCH_CAPABILITY,
            status=status,  # type: ignore[arg-type]
            data=data,
            data_quality=DataQuality(
                completeness=0.0,
                quality_status="INVALID",
                known_unavailable=list(known_unavailable or []),
            ),
            provenance=[],
            error_code=error_code,
            error_message=error_message,
        )
