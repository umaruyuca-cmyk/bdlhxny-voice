from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from stockwise_analysis.contracts.analysis import AnalysisInput, AnalysisResult
from stockwise_analysis.contracts.observation import (
    DataQuality,
    Observation,
    ProvenanceRecord,
)
from stockwise_analysis.domain.analysis_engine import analyze
from stockwise_analysis.domains.contracts import DomainBudget, DomainOperation
from stockwise_analysis.domains.finance.authorization import (
    ANALYSIS_CAPABILITY,
    FinanceCapabilityAuthorizationPolicy,
)
from stockwise_analysis.domains.finance.contracts import (
    FinancialDomainRequest,
    FinancialInstrument,
    FinancialIntent,
)
from stockwise_analysis.domains.finance.planner import FinancePlanner
from stockwise_analysis.domains.finance.runtime import FinanceRuntime
from stockwise_analysis.tools.capabilities import build_default_capability_registry


class FakeFinanceExecutor:
    def __init__(self, unavailable_capabilities: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self.unavailable_capabilities = unavailable_capabilities or set()

    async def execute(
        self,
        capability: str,
        arguments: dict[str, Any],
        *,
        request_id: str,
    ) -> Observation | AnalysisResult:
        self.calls.append(capability)
        if capability in self.unavailable_capabilities:
            return Observation(
                observation_id=f"obs-{len(self.calls)}",
                capability=capability,
                status="UNAVAILABLE",
                data_quality=DataQuality(
                    quality_status="INVALID",
                    known_unavailable=[capability],
                ),
                error_code="FIXTURE_UNAVAILABLE",
                error_message=f"{capability} unavailable",
            )
        if capability == ANALYSIS_CAPABILITY:
            return analyze(AnalysisInput.model_validate(arguments))

        data: Any
        if capability == "market.get_realtime_quote":
            data = {"symbol": "600519", "price": 1500.0, "date": "2026-08-10"}
        elif capability == "market.get_historical_prices":
            data = [
                {
                    "date": (date(2026, 6, 1) + timedelta(days=index)).isoformat(),
                    "open": 100.0 + index,
                    "high": 101.0 + index,
                    "low": 99.0 + index,
                    "close": 100.5 + index,
                    "volume": 1000 + index,
                }
                for index in range(60)
            ]
        elif capability == "market.get_financial_statements":
            data = {"revenue": 1000.0, "net_profit": 300.0}
        elif capability == "market.get_valuation":
            data = {"pe": 20.0, "pb": 6.0}
        elif capability == "market.get_industry_context":
            data = {"industry": "白酒"}
        elif capability == "market.get_money_flow":
            data = {"net_inflow": 1_000_000}
        elif capability == "market.get_news":
            data = {"items": [{"title": "公司公告"}]}
        elif capability == "research.web_search":
            data = {"results": [{"title": "公开资料", "url": "https://example.com"}]}
        else:
            raise AssertionError(f"unexpected capability: {capability}")
        return Observation(
            observation_id=f"obs-{len(self.calls)}",
            capability=capability,
            status="SUCCESS",
            data=data,
            data_quality=DataQuality(completeness=1.0, quality_status="OK"),
            provenance=[
                ProvenanceRecord(
                    source="provider-a",
                    tool=capability,
                    request_id=request_id,
                    as_of="2026-08-10T10:00:00+08:00",
                    retrieved_at="2026-08-10T10:00:01+08:00",
                )
            ],
        )


def build_runtime(executor: FakeFinanceExecutor) -> FinanceRuntime:
    registry = build_default_capability_registry()
    return FinanceRuntime(
        planner=FinancePlanner(registry),
        authorization=FinanceCapabilityAuthorizationPolicy(registry),
        executor=executor,
    )


EXPECTED_DEFAULT_DATA_CAPABILITIES = {
    "market_snapshot": ["market.get_realtime_quote"],
    "technical": [
        "market.get_realtime_quote",
        "market.get_historical_prices",
    ],
    "fundamental": [
        "market.get_realtime_quote",
        "market.get_financial_statements",
    ],
    "valuation": [
        "market.get_realtime_quote",
        "market.get_valuation",
    ],
    "comprehensive": [
        "market.get_realtime_quote",
        "market.get_historical_prices",
        "market.get_financial_statements",
        "market.get_valuation",
        "market.get_industry_context",
        "market.get_money_flow",
        "market.get_news",
        "research.web_search",
    ],
}

UNAVAILABLE_REQUIRED_CAPABILITY = {
    "market_snapshot": "market.get_realtime_quote",
    "technical": "market.get_historical_prices",
    "fundamental": "market.get_financial_statements",
    "valuation": "market.get_valuation",
    "comprehensive": "market.get_historical_prices",
}


def request_for(
    analysis_type: str = "market_snapshot",
    *,
    requested_topics: set[str] | None = None,
    intent: FinancialIntent = FinancialIntent.STOCK_RESEARCH,
    operations: set[DomainOperation] | None = None,
    tool_call_limit: int = 20,
) -> FinancialDomainRequest:
    return FinancialDomainRequest(
        request_id=f"request-{analysis_type}",
        authenticated_user_id="user-1",
        objective="执行兼容股票研究",
        financial_intent=intent,
        analysis_type=analysis_type,
        requested_topics=requested_topics or set(),
        instruments=[FinancialInstrument(symbol="600519", name="贵州茅台")],
        authorized_operations=operations or {
            DomainOperation.READ_MARKET_DATA,
            DomainOperation.READ_PUBLIC_RESEARCH,
            DomainOperation.RUN_ANALYSIS,
        },
        budget=DomainBudget(
            tool_call_limit=tool_call_limit,
            runtime_seconds=10,
            model_call_limit=0,
        ),
    )


@pytest.mark.parametrize(
    "analysis_type",
    ["market_snapshot", "technical", "fundamental", "valuation", "comprehensive"],
)
@pytest.mark.asyncio
async def test_five_analysis_types_use_the_shared_analysis_capability(analysis_type: str) -> None:
    executor = FakeFinanceExecutor()
    outcome = await build_runtime(executor).run(request_for(analysis_type))

    assert outcome.status == "COMPLETE"
    assert outcome.analysis_result is not None
    assert outcome.stock_research_result is not None
    assert outcome.stock_research_result.coverage == "COMPLETE"
    assert outcome.stock_research_result.confidence.level == "HIGH"
    research = outcome.stock_research_result
    assert research.market_snapshot is not None
    assert (research.technicals is not None) == (
        analysis_type in {"technical", "comprehensive"}
    )
    assert (research.fundamentals is not None) == (
        analysis_type in {"fundamental", "comprehensive"}
    )
    assert (research.valuation is not None) == (
        analysis_type in {"valuation", "comprehensive"}
    )
    assert (research.money_flow is not None) == (analysis_type == "comprehensive")
    assert (research.industry_context is not None) == (
        analysis_type == "comprehensive"
    )
    assert bool(research.events) == (analysis_type == "comprehensive")
    assert research.scenarios == []
    assert set(outcome.analysis_result.limitations) <= set(research.limitations)
    assert all(item.evidence_ids or item.calculation_ids for item in research.findings)
    if research.technicals is not None:
        assert (
            research.technicals.indicators
            == outcome.analysis_result.calculated_indicators
        )
    assert outcome.analysis_result.analysis_id == f"request-{analysis_type}"
    assert executor.calls == [
        *EXPECTED_DEFAULT_DATA_CAPABILITIES[analysis_type],
        ANALYSIS_CAPABILITY,
    ]
    assert all(not name.startswith(("portfolio.", "user.")) for name in executor.calls)


@pytest.mark.parametrize("analysis_type", list(EXPECTED_DEFAULT_DATA_CAPABILITIES))
@pytest.mark.asyncio
async def test_each_analysis_type_reports_required_data_unavailability(
    analysis_type: str,
) -> None:
    unavailable = UNAVAILABLE_REQUIRED_CAPABILITY[analysis_type]
    executor = FakeFinanceExecutor({unavailable})

    outcome = await build_runtime(executor).run(request_for(analysis_type))

    assert outcome.status == "LIMITED"
    assert outcome.stock_research_result is not None
    assert outcome.stock_research_result.coverage == "LIMITED"
    assert outcome.stock_research_result.findings == []
    assert any(item.code == "FIXTURE_UNAVAILABLE" for item in outcome.errors)
    assert unavailable in outcome.analysis_result.data_quality.known_unavailable


@pytest.mark.parametrize("analysis_type", list(EXPECTED_DEFAULT_DATA_CAPABILITIES))
@pytest.mark.asyncio
async def test_each_analysis_type_reserves_budget_for_required_analysis(
    analysis_type: str,
) -> None:
    executor = FakeFinanceExecutor()
    required_data_calls = sum(
        capability in {
            "market.get_realtime_quote",
            "market.get_historical_prices",
            "market.get_financial_statements",
            "market.get_valuation",
        }
        for capability in EXPECTED_DEFAULT_DATA_CAPABILITIES[analysis_type]
    )

    outcome = await build_runtime(executor).run(
        request_for(analysis_type, tool_call_limit=required_data_calls)
    )

    assert outcome.status == "LIMITED"
    assert outcome.errors[0].code == "BUDGET_EXHAUSTED"
    assert executor.calls == []


@pytest.mark.asyncio
async def test_explicit_topic_is_bounded_by_analysis_policy() -> None:
    rejected_executor = FakeFinanceExecutor()
    rejected = await build_runtime(rejected_executor).run(
        request_for("market_snapshot", requested_topics={"news"})
    )
    assert rejected.status == "FAILED"
    assert rejected.errors[0].code == "REQUESTED_TOPIC_NOT_ALLOWED"
    assert rejected_executor.calls == []

    accepted_executor = FakeFinanceExecutor()
    accepted = await build_runtime(accepted_executor).run(
        request_for("technical", requested_topics={"news", "money_flow"})
    )
    assert accepted.status in {"COMPLETE", "PARTIAL"}
    assert "market.get_news" in accepted_executor.calls
    assert "market.get_money_flow" in accepted_executor.calls


@pytest.mark.parametrize(
    ("analysis_type", "topic", "capability"),
    [
        ("technical", "news", "market.get_news"),
        ("fundamental", "web_research", "research.web_search"),
        ("valuation", "industry", "market.get_industry_context"),
        ("comprehensive", "news", "market.get_news"),
    ],
)
@pytest.mark.asyncio
async def test_optional_policies_accept_their_explicit_topics(
    analysis_type: str,
    topic: str,
    capability: str,
) -> None:
    executor = FakeFinanceExecutor()

    outcome = await build_runtime(executor).run(
        request_for(analysis_type, requested_topics={topic})
    )

    assert outcome.status in {"COMPLETE", "PARTIAL", "LIMITED"}
    assert capability in executor.calls


@pytest.mark.asyncio
async def test_required_authorization_fails_before_external_calls() -> None:
    executor = FakeFinanceExecutor()
    outcome = await build_runtime(executor).run(
        request_for(
            "technical",
            operations={DomainOperation.READ_MARKET_DATA},
        )
    )
    assert outcome.status == "FAILED"
    assert outcome.errors[0].code == "REQUIRED_CAPABILITY_NOT_AUTHORIZED"
    assert executor.calls == []


@pytest.mark.asyncio
async def test_optional_public_research_permission_degrades_without_leaking_access() -> None:
    executor = FakeFinanceExecutor()
    outcome = await build_runtime(executor).run(
        request_for(
            "comprehensive",
            operations={
                DomainOperation.READ_MARKET_DATA,
                DomainOperation.RUN_ANALYSIS,
            },
        )
    )
    assert outcome.status in {"PARTIAL", "LIMITED"}
    assert "research.web_search" not in executor.calls
    assert any("research.web_search" in item for item in outcome.limitations)


@pytest.mark.asyncio
async def test_profile_permission_does_not_grant_m1_data_or_analysis_access() -> None:
    executor = FakeFinanceExecutor()
    outcome = await build_runtime(executor).run(
        request_for(
            "market_snapshot",
            operations={DomainOperation.READ_PROFILE},
        )
    )
    assert outcome.status == "FAILED"
    assert outcome.errors[0].code == "REQUIRED_CAPABILITY_NOT_AUTHORIZED"
    assert executor.calls == []


@pytest.mark.asyncio
async def test_failed_analysis_result_is_returned_as_a_stable_domain_error() -> None:
    class FailedAnalysisExecutor(FakeFinanceExecutor):
        async def execute(
            self,
            capability: str,
            arguments: dict[str, Any],
            *,
            request_id: str,
        ) -> Observation | AnalysisResult:
            if capability == "analysis.run_analysis":
                self.calls.append(capability)
                return AnalysisResult(
                    analysis_id=request_id,
                    status="FAILED",
                    limitations=["analysis fixture failed"],
                )
            return await super().execute(
                capability,
                arguments,
                request_id=request_id,
            )

    executor = FailedAnalysisExecutor()
    outcome = await build_runtime(executor).run(request_for("market_snapshot"))

    assert outcome.status == "FAILED"
    assert outcome.stock_research_result is not None
    assert outcome.stock_research_result.coverage == "LIMITED"
    assert outcome.errors[0].code == "ANALYSIS_FAILED"
    assert outcome.errors[0].message == "analysis fixture failed"


@pytest.mark.asyncio
async def test_builder_failure_returns_stable_error_and_preserves_analysis_result() -> None:
    class BrokenBuilder:
        def build(self, **_kwargs: Any) -> None:
            raise ValueError("private builder detail")

    executor = FakeFinanceExecutor()
    registry = build_default_capability_registry()
    runtime = FinanceRuntime(
        planner=FinancePlanner(registry),
        authorization=FinanceCapabilityAuthorizationPolicy(registry),
        executor=executor,
        research_builder=BrokenBuilder(),  # type: ignore[arg-type]
    )

    outcome = await runtime.run(request_for("market_snapshot"))

    assert outcome.status == "FAILED"
    assert outcome.analysis_result is not None
    assert outcome.stock_research_result is None
    assert outcome.errors[0].code == "STOCK_RESEARCH_BUILD_FAILED"
    assert "private builder detail" not in outcome.model_dump_json()


@pytest.mark.parametrize(
    "intent",
    [
        FinancialIntent.SUITABILITY,
        FinancialIntent.PORTFOLIO_IMPACT,
        FinancialIntent.GOAL_PLANNING,
    ],
)
@pytest.mark.asyncio
async def test_disabled_intents_have_stable_errors(intent: FinancialIntent) -> None:
    disabled_executor = FakeFinanceExecutor()
    analysis_type = (
        "comprehensive"
        if intent == FinancialIntent.SUITABILITY
        else "market_snapshot"
    )
    disabled = await build_runtime(disabled_executor).run(
        request_for(analysis_type, intent=intent)
    )
    assert disabled.status == "FAILED"
    assert disabled.errors[0].code == "ACTION_NOT_ENABLED"
    assert disabled_executor.calls == []


@pytest.mark.asyncio
async def test_insufficient_budget_has_stable_error() -> None:
    budget_executor = FakeFinanceExecutor()
    limited = await build_runtime(budget_executor).run(
        request_for("technical", tool_call_limit=1)
    )
    assert limited.status == "LIMITED"
    assert limited.errors[0].code == "BUDGET_EXHAUSTED"
    assert budget_executor.calls == []
