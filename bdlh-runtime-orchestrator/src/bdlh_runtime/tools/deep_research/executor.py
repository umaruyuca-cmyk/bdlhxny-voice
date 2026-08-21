"""DeepResearchToolExecutor：固定复合研究 Capability（ADR-016 APPROVED 开发阶段）。

默认 ``enabled=False``：返回 UNAVAILABLE，不跑编排、不碰 SearXNG。
``enabled=True`` 时必须注入 ``AtomicSearchPort`` 与 ``DeepResearchModel``。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from bdlh_runtime.contracts.observation import DataQuality, Observation, ProvenanceRecord
from bdlh_runtime.tools.deep_research.assembly import assemble_research_bundle
from bdlh_runtime.tools.deep_research.atomic_search import AtomicSearchPort
from bdlh_runtime.tools.deep_research.call_policy import evaluate_deep_research_trigger
from bdlh_runtime.tools.deep_research.contracts import DEEP_SEARCH_CAPABILITY, DeepResearchRequest
from bdlh_runtime.tools.deep_research.models import DeepResearchModel
from bdlh_runtime.tools.deep_research.orchestration import run_deep_research


class DeepResearchToolExecutor:
    """固定复合研究 Capability 执行器。"""

    def __init__(
        self,
        *,
        enabled: bool = False,
        atomic_search: AtomicSearchPort | None = None,
        research_model: DeepResearchModel | None = None,
    ) -> None:
        if enabled and research_model is None:
            raise ValueError("research_model is required when DeepResearchToolExecutor is enabled")
        if enabled and atomic_search is None:
            raise ValueError("atomic_search is required when DeepResearchToolExecutor is enabled")
        self._enabled = enabled
        self._atomic_search = atomic_search
        self._research_model = research_model

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
                    "research.deep_search is feature-gated (ADR-016); use research.web_search for ordinary queries"
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

        if self._atomic_search is None or self._research_model is None:
            return self._observation(
                status="UNAVAILABLE",
                error_code="ATOMIC_SEARCH_UNAVAILABLE",
                error_message="AtomicSearchPort or DeepResearchModel is not configured",
                data=None,
                known_unavailable=[DEEP_SEARCH_CAPABILITY],
            )

        trigger = evaluate_deep_research_trigger(
            request,
            feature_enabled=True,
            in_allowed=True,
            entitled=True,
            sync_budget_ok=True,
            expected_independent_queries=(max(len(request.research_topics), len(request.success_criteria), 1)),
        )
        bundle = await run_deep_research(
            request,
            atomic_search=self._atomic_search,
            deep_trigger_reasons=list(trigger.reasons or trigger.deep_trigger_reasons),
            research_model=self._research_model,
        )
        obs_status = "SUCCESS" if bundle.status in {"PARTIAL", "COMPLETE"} else "FAILED"
        if bundle.status in {"LIMITED", "NEEDS_CLARIFICATION"}:
            obs_status = "PARTIAL"
        unavailable_codes = {"ATOMIC_SEARCH_UNAVAILABLE", "ATOMIC_SEARCH_RATE_LIMITED"}
        if bundle.status == "FAILED" and unavailable_codes.intersection(bundle.limitations):
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
                    retrieved_at=datetime.now(UTC).isoformat(),
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
