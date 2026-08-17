from __future__ import annotations

import pytest

from bdlh_runtime.cognitive.contracts import CognitiveActionType, InputEvent
from bdlh_runtime.cognitive.orchestrator import CognitiveOrchestrator
from bdlh_runtime.domains.contracts import (
    ConfidenceAssessment,
    DomainFact,
    DomainOperation,
    DomainOutcome,
    RequiredUserDecision,
)
from bdlh_runtime.domains.finance.cognitive_adapter import (
    FinanceCognitiveContinuation,
    FinanceCognitiveSelector,
    InMemoryVerifiedEntityStore,
)
from bdlh_runtime.domains.finance.contracts import (
    FinancialDomainRequest,
    FinancialInstrument,
    InstrumentCandidate,
    InstrumentResolutionOutcome,
    InstrumentResolutionRequest,
)


def _event(message: str, *, event_id: str = "event-1") -> InputEvent:
    return InputEvent(
        event_id=event_id,
        user_id="user-1",
        session_id="session-1",
        message=message,
    )


def _candidate() -> InstrumentCandidate:
    return InstrumentCandidate(
        instrument=FinancialInstrument(symbol="600519", name="贵州茅台"),
        canonical_symbol="600519",
        exchange="SSE",
        currency="CNY",
        match_type="EXACT_NAME",
        source_refs=["market-master:resolve"],
    )


class FinanceDispatcher:
    def __init__(self, *, ambiguous: bool = False) -> None:
        self.ambiguous = ambiguous
        self.requests: list[object] = []

    async def dispatch(self, request: object) -> DomainOutcome:
        self.requests.append(request)
        if isinstance(request, InstrumentResolutionRequest):
            if self.ambiguous:
                return InstrumentResolutionOutcome(
                    request_id=request.request_id,
                    status="WAITING_USER",
                    resolution_status="AMBIGUOUS",
                    candidates=[_candidate()],
                    confidence=ConfidenceAssessment(
                        level="LOW", reasons=["ambiguous"], coverage_status="PARTIAL"
                    ),
                    limitations=["需要确认候选"],
                    required_user_decisions=[RequiredUserDecision(
                        decision_id="instrument_candidate",
                        question="请选择贵州茅台（600519，SSE）",
                        reason="候选不唯一",
                        allowed_choices=["600519@SSE"],
                    )],
                )
            return InstrumentResolutionOutcome(
                request_id=request.request_id,
                status="COMPLETE",
                resolution_status="RESOLVED",
                selected=_candidate(),
                candidates=[_candidate()],
                confidence=ConfidenceAssessment(
                    level="HIGH", reasons=["validated"], coverage_status="COMPLETE"
                ),
            )
        assert isinstance(request, FinancialDomainRequest)
        return DomainOutcome(
            request_id=request.request_id,
            domain="finance",
            status="COMPLETE",
            established_facts=[DomainFact(
                fact_id="quote-1",
                statement="贵州茅台的受控行情研究已完成",
                source_refs=["quote:600519"],
                directness="DIRECT",
            )],
            confidence=ConfidenceAssessment(
                level="HIGH", reasons=["validated"], coverage_status="COMPLETE"
            ),
        )


def _app(dispatcher: FinanceDispatcher, store: InMemoryVerifiedEntityStore | None = None) -> CognitiveOrchestrator:
    entities = store or InMemoryVerifiedEntityStore()
    return CognitiveOrchestrator(
        selector=FinanceCognitiveSelector(entities),
        dispatcher=dispatcher,
        continuation=FinanceCognitiveContinuation(entities),
        enabled_domains=frozenset({"finance"}),
        authorized_operations=frozenset(
            {
                DomainOperation.READ_MARKET_DATA.value,
                DomainOperation.READ_PUBLIC_RESEARCH.value,
                DomainOperation.READ_PORTFOLIO.value,
                DomainOperation.READ_PROFILE.value,
                DomainOperation.READ_FINANCIAL_GOALS.value,
                DomainOperation.RUN_ANALYSIS.value,
            }
        ),
    )


@pytest.mark.asyncio
async def test_natural_language_name_resolves_then_researches_in_one_run() -> None:
    dispatcher = FinanceDispatcher()

    result = await _app(dispatcher).run(_event("贵州茅台今天怎么样"))

    assert [type(item) for item in dispatcher.requests] == [
        InstrumentResolutionRequest,
        FinancialDomainRequest,
    ]
    assert result.response.response_kind == "DOMAIN_RESULT"
    assert result.response.evidence_refs == ["quote:600519"]
    assert [item.action_type for item in result.state.action_history] == [
        CognitiveActionType.INVOKE_DOMAIN,
        CognitiveActionType.INVOKE_DOMAIN,
    ]
    dumped_state = result.state.model_dump(mode="json")
    assert "authorized_operations" not in str(dumped_state)
    assert result.state.domain_request_refs == ["event-1:resolve", "event-1:research"]


@pytest.mark.asyncio
async def test_ambiguous_resolution_asks_with_candidate_instead_of_guessing() -> None:
    dispatcher = FinanceDispatcher(ambiguous=True)

    result = await _app(dispatcher).run(_event("平安今天怎么样"))

    assert len(dispatcher.requests) == 1
    assert result.response.response_kind == "ASK_USER"
    assert "600519" in result.response.message
    assert result.response.next_steps


@pytest.mark.asyncio
async def test_user_can_select_a_previous_ambiguous_candidate() -> None:
    store = InMemoryVerifiedEntityStore()
    dispatcher = FinanceDispatcher(ambiguous=True)
    app = _app(dispatcher, store)
    await app.run(_event("平安今天怎么样", event_id="event-1"))
    dispatcher.ambiguous = False
    dispatcher.requests.clear()

    result = await app.run(_event("选择 600519@SSE", event_id="event-2"))

    assert len(dispatcher.requests) == 1
    request = dispatcher.requests[0]
    assert isinstance(request, FinancialDomainRequest)
    assert request.instruments[0].symbol == "600519"
    assert result.response.response_kind == "DOMAIN_RESULT"


@pytest.mark.asyncio
async def test_missing_instrument_asks_for_name_alias_or_code() -> None:
    dispatcher = FinanceDispatcher()

    result = await _app(dispatcher).run(_event("分析股票怎么样"))

    assert dispatcher.requests == []
    assert result.response.response_kind == "ASK_USER"
    assert "公司名称、简称或证券代码" in result.response.message


@pytest.mark.asyncio
async def test_explicit_reference_reuses_only_session_verified_entity() -> None:
    store = InMemoryVerifiedEntityStore()
    dispatcher = FinanceDispatcher()
    app = _app(dispatcher, store)
    await app.run(_event("贵州茅台今天怎么样", event_id="event-1"))
    dispatcher.requests.clear()

    result = await app.run(_event("它今天跌了多少", event_id="event-2"))

    assert len(dispatcher.requests) == 1
    request = dispatcher.requests[0]
    assert isinstance(request, FinancialDomainRequest)
    assert request.instruments[0].symbol == "600519"
    assert result.response.response_kind == "DOMAIN_RESULT"


@pytest.mark.asyncio
async def test_ellipsis_followup_reuses_verified_entity_but_new_topic_does_not() -> None:
    store = InMemoryVerifiedEntityStore()
    dispatcher = FinanceDispatcher()
    app = _app(dispatcher, store)
    await app.run(_event("贵州茅台今天怎么样", event_id="event-1"))
    dispatcher.requests.clear()

    followup = await app.run(_event("估值呢", event_id="event-2"))
    request = dispatcher.requests[0]
    assert isinstance(request, FinancialDomainRequest)
    assert request.analysis_type == "valuation"
    assert followup.response.response_kind == "DOMAIN_RESULT"

    dispatcher.requests.clear()
    new_topic = await app.run(_event("新能源行业怎么样", event_id="event-3"))
    assert len(dispatcher.requests) == 2  # 假 Resolver 固定返回茅台；关键是先解析新提及
    assert isinstance(dispatcher.requests[0], InstrumentResolutionRequest)
    assert dispatcher.requests[0].mention.normalized_text == "新能源行业"
    assert new_topic.response.response_kind == "DOMAIN_RESULT"


@pytest.mark.asyncio
async def test_stable_knowledge_responds_without_domain_data() -> None:
    dispatcher = FinanceDispatcher()

    result = await _app(dispatcher).run(_event("什么是市盈率"))

    assert dispatcher.requests == []
    assert result.response.response_kind == "ANSWER"
    assert "市盈率" in result.response.message


@pytest.mark.asyncio
async def test_verified_reference_expires_after_the_configured_turn_gap() -> None:
    store = InMemoryVerifiedEntityStore(max_reference_turn_gap=1)
    dispatcher = FinanceDispatcher()
    app = _app(dispatcher, store)
    await app.run(_event("贵州茅台今天怎么样", event_id="event-1"))
    await app.run(_event("什么是市盈率", event_id="event-2"))
    dispatcher.requests.clear()

    result = await app.run(_event("它今天怎么样", event_id="event-3"))

    assert dispatcher.requests == []
    assert result.response.response_kind == "ASK_USER"
    assert result.response.audit_codes == ["REFERENCE_NOT_RESOLVED"]


@pytest.mark.asyncio
async def test_knowledge_prefix_with_issuer_name_still_resolves() -> None:
    dispatcher = FinanceDispatcher()

    result = await _app(dispatcher).run(_event("什么是贵州茅台"))

    assert [type(item) for item in dispatcher.requests] == [
        InstrumentResolutionRequest,
        FinancialDomainRequest,
    ]
    assert result.response.response_kind == "DOMAIN_RESULT"


@pytest.mark.asyncio
async def test_suitability_only_request_does_not_invoke_dead_intent() -> None:
    store = InMemoryVerifiedEntityStore()
    dispatcher = FinanceDispatcher()
    app = _app(dispatcher, store)
    await app.run(_event("贵州茅台今天怎么样", event_id="event-1"))
    dispatcher.requests.clear()

    result = await app.run(_event("它适合我吗", event_id="event-2"))

    assert dispatcher.requests == []
    assert result.response.response_kind == "ANSWER"
    assert result.response.audit_codes == ["SUITABILITY_NOT_ENABLED"]
    assert "尚未启用" in result.response.message
