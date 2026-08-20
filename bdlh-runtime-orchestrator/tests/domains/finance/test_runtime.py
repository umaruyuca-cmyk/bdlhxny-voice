from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from tests.helpers_registry import seeded_snapshot

from bdlh_runtime.contracts.analysis import AnalysisInput, AnalysisResult
from bdlh_runtime.contracts.observation import (
    DataQuality,
    Observation,
    ProvenanceRecord,
)
from bdlh_runtime.domain.analysis_engine import analyze
from bdlh_runtime.domains.contracts import DomainBudget, DomainOperation
from bdlh_runtime.domains.finance.authorization import (
    ANALYSIS_CAPABILITY,
    FinanceCapabilityAuthorizationPolicy,
)
from bdlh_runtime.domains.finance.contracts import (
    FinancialDomainRequest,
    FinancialInstrument,
    FinancialIntent,
)
from bdlh_runtime.domains.finance.planner import FinancePlanner
from bdlh_runtime.domains.finance.runtime import FinanceRuntime
from bdlh_runtime.tools.capabilities import load_capability_registry


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
        if capability == "market.resolve_instrument":
            data = {"symbol": "600519", "name": "贵州茅台"}
        elif capability == "market.get_realtime_quote":
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
    registry = load_capability_registry(seeded_snapshot())
    return FinanceRuntime(
        planner=FinancePlanner(topic_capabilities=_TOPIC_CAPABILITIES),
        authorization=FinanceCapabilityAuthorizationPolicy(registry),
        executor=executor,
    )


def _topic_map() -> dict[str, list[str]]:
    snapshot = seeded_snapshot()
    return {
        topic: snapshot.topic_capabilities_for(topic) for topic in ("news", "money_flow", "industry", "web_research")
    }


_TOPIC_CAPABILITIES = _topic_map()


#: 重写语义：STOCK_RESEARCH 统一基线研究面板（不随问话体裁变化）
EXPECTED_DEFAULT_DATA_CAPABILITIES = [
    "market.resolve_instrument",
    "market.get_realtime_quote",
    "market.get_historical_prices",
    "market.get_financial_statements",
    "market.get_valuation",
    "market.get_industry_context",
    "market.get_news",
]

#: 面板中的关键数据能力（预算保留与不可用降级参数化）
UNAVAILABLE_REQUIRED_CAPABILITY = {
    "market.get_realtime_quote",
    "market.get_historical_prices",
    "market.get_financial_statements",
    "market.get_valuation",
}


def request_for(
    *,
    request_id: str = "request-research",
    requested_topics: set[str] | None = None,
    intent: FinancialIntent = FinancialIntent.STOCK_RESEARCH,
    operations: set[DomainOperation] | None = None,
    tool_call_limit: int = 20,
) -> FinancialDomainRequest:
    return FinancialDomainRequest(
        request_id=request_id,
        authenticated_user_id="user-1",
        objective="执行兼容股票研究",
        financial_intent=intent,
        requested_topics=requested_topics or set(),
        instruments=[FinancialInstrument(symbol="600519", name="贵州茅台")],
        authorized_operations=operations
        or {
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


@pytest.mark.asyncio
async def test_explicit_topics_attach_to_any_research_request() -> None:
    """重写语义：topic 附加无类型门槛（类型白名单已删），随时可请求。"""
    executor = FakeFinanceExecutor()
    outcome = await build_runtime(executor).run(request_for(requested_topics={"news", "money_flow"}))
    assert outcome.status in {"COMPLETE", "PARTIAL"}
    assert "market.get_news" in executor.calls
    assert "market.get_money_flow" in executor.calls


@pytest.mark.parametrize(
    ("topic", "capability"),
    [
        ("news", "market.get_news"),
        ("web_research", "research.web_search"),
        ("industry", "market.get_industry_context"),
        ("money_flow", "market.get_money_flow"),
    ],
)
@pytest.mark.asyncio
async def test_topics_attach_their_topic_capabilities(
    topic: str,
    capability: str,
) -> None:
    executor = FakeFinanceExecutor()

    outcome = await build_runtime(executor).run(request_for(requested_topics={topic}))

    assert outcome.status in {"COMPLETE", "PARTIAL", "LIMITED"}
    assert capability in executor.calls


@pytest.mark.asyncio
async def test_required_authorization_fails_before_external_calls() -> None:
    executor = FakeFinanceExecutor()
    outcome = await build_runtime(executor).run(
        request_for(
            operations={DomainOperation.READ_MARKET_DATA},
        )
    )
    assert outcome.status == "FAILED"
    assert outcome.errors[0].code == "REQUIRED_CAPABILITY_NOT_AUTHORIZED"
    assert executor.calls == []


@pytest.mark.asyncio
async def test_optional_public_research_permission_degrades_without_leaking_access() -> None:
    """重写语义：web_research 是 optional 附加——无 READ_PUBLIC_RESEARCH 时
    降级为 limitation，不失败、不泄漏访问。"""
    executor = FakeFinanceExecutor()
    outcome = await build_runtime(executor).run(
        request_for(
            requested_topics={"web_research"},
            operations={
                DomainOperation.READ_MARKET_DATA,
                DomainOperation.RUN_ANALYSIS,
            },
        )
    )
    assert outcome.status in {"COMPLETE", "PARTIAL", "LIMITED"}
    assert "research.web_search" not in executor.calls
    assert any("research.web_search" in item for item in outcome.limitations)


@pytest.mark.asyncio
async def test_profile_permission_does_not_grant_m1_data_or_analysis_access() -> None:
    executor = FakeFinanceExecutor()
    outcome = await build_runtime(executor).run(
        request_for(
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
    outcome = await build_runtime(executor).run(request_for())

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
    registry = load_capability_registry(seeded_snapshot())
    runtime = FinanceRuntime(
        planner=FinancePlanner(topic_capabilities=_TOPIC_CAPABILITIES),
        authorization=FinanceCapabilityAuthorizationPolicy(registry),
        executor=executor,
        research_builder=BrokenBuilder(),  # type: ignore[arg-type]
    )

    outcome = await runtime.run(request_for())

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
    disabled = await build_runtime(disabled_executor).run(request_for(intent=intent))
    assert disabled.status == "FAILED"
    assert disabled.errors[0].code == "ACTION_NOT_ENABLED"
    assert disabled_executor.calls == []


@pytest.mark.asyncio
async def test_insufficient_budget_has_stable_error() -> None:
    budget_executor = FakeFinanceExecutor()
    limited = await build_runtime(budget_executor).run(request_for(tool_call_limit=1))
    assert limited.status == "LIMITED"
    assert limited.errors[0].code == "BUDGET_EXHAUSTED"
    assert budget_executor.calls == []
