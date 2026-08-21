"""G8：PORTFOLIO_IMPACT / GOAL_PLANNING 运行时回归。"""

from __future__ import annotations

from typing import Any

import pytest
from tests.helpers_registry import seeded_snapshot

from bdlh_runtime.contracts.analysis import AnalysisInput, AnalysisResult
from bdlh_runtime.contracts.observation import DataQuality, Observation, ProvenanceRecord
from bdlh_runtime.domain.analysis_engine import analyze
from bdlh_runtime.domains.contracts import DomainBudget, DomainOperation, GoalRef
from bdlh_runtime.domains.finance.authorization import (
    ANALYSIS_CAPABILITY,
    FinanceCapabilityAuthorizationPolicy,
)
from bdlh_runtime.domains.finance.contracts import FinancialDomainRequest, FinancialIntent
from bdlh_runtime.domains.finance.planner import FinancePlanner
from bdlh_runtime.domains.finance.runtime import FinanceRuntime
from bdlh_runtime.domains.finance.snapshot_builder import (
    ACCOUNT_CAPABILITY,
    NORMALIZED_USER_DATA_SCHEMA,
    POSITIONS_CAPABILITY,
    RISK_PROFILE_CAPABILITY,
)
from bdlh_runtime.domains.finance.valuation_builder import PortfolioValuationBuilder
from bdlh_runtime.tools.capabilities import load_capability_registry

_USER = "user-1"


class ImpactExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(
        self,
        capability: str,
        arguments: dict[str, Any],
        *,
        request_id: str,
    ) -> Observation | AnalysisResult:
        self.calls.append(capability)
        if capability == ANALYSIS_CAPABILITY:
            return analyze(AnalysisInput.model_validate(arguments))
        if capability == "portfolio.build_current_valuation":
            return PortfolioValuationBuilder().build(
                positions_observation=Observation.model_validate(arguments["positions_observation"]),
                account_observation=Observation.model_validate(arguments["account_observation"]),
                quote_observations=[
                    Observation.model_validate(item) for item in arguments["quote_observations"]
                ],
                authenticated_user_id=arguments["authenticated_user_id"],
            )
        if capability == POSITIONS_CAPABILITY:
            data = {
                "schema_version": NORMALIZED_USER_DATA_SCHEMA,
                "user_id": _USER,
                "data_mode": "TEST_FIXTURE",
                "positions": [
                    {
                        "symbol": "600519",
                        "exchange": "SSE",
                        "currency": "CNY",
                        "quantity": 100,
                        "industry": "白酒",
                        "source": "pos-1",
                    }
                ],
            }
        elif capability == ACCOUNT_CAPABILITY:
            data = {
                "schema_version": NORMALIZED_USER_DATA_SCHEMA,
                "user_id": _USER,
                "data_mode": "TEST_FIXTURE",
                "account": {"cash": 50_000, "currency": "CNY", "source": "acct-1"},
                "liquidity": {},
            }
        elif capability == RISK_PROFILE_CAPABILITY:
            data = {
                "schema_version": NORMALIZED_USER_DATA_SCHEMA,
                "user_id": _USER,
                "data_mode": "TEST_FIXTURE",
                "risk_profile": {
                    "risk_level": "BALANCED",
                    "max_loss_tolerance_pct": 20.0,
                    "source": "risk-1",
                },
            }
        elif capability == "market.get_realtime_quote":
            data = {
                "symbol": arguments.get("symbol") or "600519",
                "exchange": "SSE",
                "currency": "CNY",
                "price": 1800.0,
                "as_of": "2026-08-17T01:00:00Z",
            }
        else:
            raise AssertionError(f"unexpected capability: {capability}")
        return Observation(
            observation_id=f"obs-{len(self.calls)}-{capability.split('.')[-1]}",
            capability=capability,
            status="SUCCESS",
            data=data,
            data_quality=DataQuality(completeness=1.0, quality_status="OK"),
            provenance=[
                ProvenanceRecord(
                    source="fixture",
                    tool=capability,
                    request_id=request_id,
                    retrieved_at="2026-08-17T00:00:00+00:00",
                    as_of="2026-08-17T00:00:00Z",
                )
            ],
        )


def _runtime(executor: ImpactExecutor) -> FinanceRuntime:
    return FinanceRuntime(
        planner=FinancePlanner(),
        authorization=FinanceCapabilityAuthorizationPolicy(load_capability_registry(seeded_snapshot())),
        executor=executor,
        execution_environment="test",
    )


def _request(intent: FinancialIntent, *, goals: list[GoalRef] | None = None) -> FinancialDomainRequest:
    ops = {
        DomainOperation.READ_PORTFOLIO,
        DomainOperation.READ_PROFILE,
        DomainOperation.READ_MARKET_DATA,
    }
    if intent == FinancialIntent.GOAL_PLANNING:
        ops.add(DomainOperation.READ_FINANCIAL_GOALS)
    return FinancialDomainRequest(
        request_id=f"g8-{intent.value}",
        authenticated_user_id=_USER,
        objective="g8 impact",
        authorized_operations=ops,
        budget=DomainBudget(tool_call_limit=12, runtime_seconds=30),
        financial_intent=intent,
        goals=list(goals or []),
        requires_financial_snapshot=True,
    )


@pytest.mark.asyncio
async def test_portfolio_impact_builds_exposure_with_evidence() -> None:
    executor = ImpactExecutor()
    outcome = await _runtime(executor).run(_request(FinancialIntent.PORTFOLIO_IMPACT))

    assert outcome.status in {"COMPLETE", "PARTIAL"}
    assert outcome.portfolio_impact is not None
    assert outcome.portfolio_impact.current_exposure
    assert "largest_position_weight_pct" in outcome.portfolio_impact.current_exposure
    assert POSITIONS_CAPABILITY in executor.calls
    assert ACCOUNT_CAPABILITY in executor.calls
    assert "portfolio.build_current_valuation" in executor.calls
    assert ANALYSIS_CAPABILITY not in executor.calls
    assert any(reason.startswith("impact evidence:") for reason in outcome.confidence.reasons)


@pytest.mark.asyncio
async def test_goal_planning_without_goals_is_limited_not_fake_complete() -> None:
    executor = ImpactExecutor()
    outcome = await _runtime(executor).run(_request(FinancialIntent.GOAL_PLANNING))

    assert outcome.status in {"LIMITED", "PARTIAL"}
    assert outcome.goal_impact is not None
    assert outcome.goal_impact.impact_level == "NONE"
    assert outcome.goal_impact.affected_goal_ids == []
    assert any("目标" in item for item in outcome.limitations)
    assert ANALYSIS_CAPABILITY not in executor.calls


@pytest.mark.asyncio
async def test_goal_planning_with_confirmed_goal() -> None:
    executor = ImpactExecutor()
    outcome = await _runtime(executor).run(
        _request(
            FinancialIntent.GOAL_PLANNING,
            goals=[
                GoalRef(
                    goal_id="g-retirement",
                    description="五年购房首付",
                    source="USER_EXPLICIT",
                    horizon="SHORT_TERM",
                )
            ],
        )
    )

    assert outcome.goal_impact is not None
    assert outcome.goal_impact.affected_goal_ids == ["g-retirement"]
    assert outcome.goal_impact.impact_level in {"LOW", "MEDIUM", "HIGH"}
