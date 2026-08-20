"""M3 Suitability 的 fail-closed 前置评估（历史模块，现网默认走 SuitabilityEngine）。

保留供对照与单测；生产路径由 ``SuitabilityEngine`` + ``suitability-v0.1`` DRAFT 规则集执行。
"""

from __future__ import annotations

from .contracts import (
    FinancialDataMode,
    FinancialSnapshot,
    StockResearchResult,
    SuitabilityAssessment,
    SuitabilityCondition,
)

PENDING_RULE_SET_VERSION = "suitability-v0.pending-adr-004-approval"
PENDING_RULE_IDS = (
    "SUIT-RESEARCH-COVERAGE-001",
    "SUIT-DATA-AUTHENTICITY-001",
    "SUIT-RISK-LEVEL-001",
    "SUIT-MAX-LOSS-001",
    "SUIT-CONCENTRATION-001",
    "SUIT-LIQUIDITY-001",
    "SUIT-GOAL-HORIZON-001",
)


class SuitabilityPreflightError(ValueError):
    """无法构造可追溯的 fail-closed 适配性结果。"""


class SuitabilityPreflight:
    """评估 M3 规则执行的输入前提，但不执行任何适配性规则。

    该类不依赖 LangGraph、MCP、HTTP、LLM 或系统时钟。获得已批准的 ADR-004
    规则集之前，只允许产出 ``INSUFFICIENT_INFORMATION``，不得产出三类个性化结论。
    """

    def evaluate(
        self,
        *,
        research: StockResearchResult,
        snapshot: FinancialSnapshot,
    ) -> SuitabilityAssessment:
        evidence_refs = sorted(set(snapshot.provenance))
        if not evidence_refs:
            raise SuitabilityPreflightError("SUITABILITY_EVIDENCE_REQUIRED: snapshot provenance is required")

        limitations = self._input_limitations(research=research, snapshot=snapshot)
        limitations.append("ADR-004 rule thresholds and aggregation are not approved")

        return SuitabilityAssessment(
            rule_set_version=PENDING_RULE_SET_VERSION,
            rule_ids=list(PENDING_RULE_IDS),
            evidence_refs=evidence_refs,
            result="INSUFFICIENT_INFORMATION",
            required_conditions=[
                SuitabilityCondition(
                    condition_id="SUITABILITY_RULE_SET_APPROVAL_REQUIRED",
                    description=(
                        "Suitability rules require an approved ADR-004 rule set before "
                        "a personalized determination can be made"
                    ),
                    verification_source="ADR-004 approval record",
                )
            ],
            reasons=["No personalized suitability determination is produced before ADR-004 approval"],
            limitations=list(dict.fromkeys(limitations)),
        )

    @staticmethod
    def _input_limitations(
        *,
        research: StockResearchResult,
        snapshot: FinancialSnapshot,
    ) -> list[str]:
        limitations: list[str] = []
        if research.coverage != "COMPLETE":
            limitations.append("Research coverage is not COMPLETE")
        if snapshot.data_mode not in {
            FinancialDataMode.LIVE,
            FinancialDataMode.USER_CONFIRMED,
        }:
            limitations.append("Snapshot data_mode cannot support personalization")
        if snapshot.completeness != "COMPLETE":
            limitations.append("Financial snapshot is not COMPLETE")
        if snapshot.risk_profile is None or snapshot.risk_profile.risk_level is None:
            limitations.append("Risk profile risk_level is unavailable")
        if snapshot.risk_profile is None or snapshot.risk_profile.max_loss_tolerance_pct is None:
            limitations.append("Risk profile max_loss_tolerance_pct is unavailable")
        if snapshot.liquidity is None or snapshot.liquidity.status == "UNKNOWN":
            limitations.append("Liquidity facts are unavailable")
        return limitations
