from __future__ import annotations

import pytest

from bdlh_runtime.cognitive.contracts import CognitiveActionType, InputEvent
from bdlh_runtime.cognitive.goal_schema import (
    ActionSpec,
    GoalSpec,
    SuccessCriterion,
    UnderstandEntities,
    UnderstandOutput,
)
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
    FinancialDomainOutcome,
    FinancialDomainRequest,
    FinancialInstrument,
    FinancialIntent,
    GoalImpact,
    InstrumentCandidate,
    InstrumentResolutionOutcome,
    InstrumentResolutionRequest,
    PortfolioImpact,
    SuitabilityAssessment,
    SuitabilityCondition,
)
from tests.helpers_understand import RuleBasedUnderstandModel


def _event(
    message: str,
    *,
    event_id: str = "event-1",
    enabled_skills: frozenset[str] | None = frozenset({"finance.stock-research"}),
) -> InputEvent:
    return InputEvent(
        event_id=event_id,
        user_id="user-1",
        session_id="session-1",
        message=message,
        enabled_skills=enabled_skills,
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
        self.suitability_condition_id = "SUITABILITY_RULE_SET_APPROVAL_REQUIRED"
        self.suitability_condition_description = "Suitability rules require an approved ADR-004 rule set"

    async def dispatch(self, request: object) -> DomainOutcome:
        self.requests.append(request)
        if isinstance(request, InstrumentResolutionRequest):
            if self.ambiguous:
                return InstrumentResolutionOutcome(
                    request_id=request.request_id,
                    status="WAITING_USER",
                    resolution_status="AMBIGUOUS",
                    candidates=[_candidate()],
                    confidence=ConfidenceAssessment(level="LOW", reasons=["ambiguous"], coverage_status="PARTIAL"),
                    limitations=["需要确认候选"],
                    required_user_decisions=[
                        RequiredUserDecision(
                            decision_id="instrument_candidate",
                            question="请选择贵州茅台（600519，SSE）",
                            reason="候选不唯一",
                            allowed_choices=["600519@SSE"],
                        )
                    ],
                )
            return InstrumentResolutionOutcome(
                request_id=request.request_id,
                status="COMPLETE",
                resolution_status="RESOLVED",
                selected=_candidate(),
                candidates=[_candidate()],
                confidence=ConfidenceAssessment(level="HIGH", reasons=["validated"], coverage_status="COMPLETE"),
            )
        assert isinstance(request, FinancialDomainRequest)
        if request.financial_intent == FinancialIntent.PORTFOLIO_IMPACT:
            return FinancialDomainOutcome(
                request_id=request.request_id,
                status="COMPLETE",
                financial_intent=request.financial_intent,
                portfolio_impact=PortfolioImpact(
                    current_exposure={"largest_position_weight_pct": 22.5},
                ),
                established_facts=[
                    DomainFact(
                        fact_id="impact-1",
                        statement="组合暴露已评估",
                        source_refs=["positions:acct-1", "valuation:v-1"],
                        directness="DIRECT",
                    )
                ],
                confidence=ConfidenceAssessment(
                    level="HIGH",
                    reasons=["impact evidence: positions:acct-1, valuation:v-1"],
                    coverage_status="COMPLETE",
                ),
            )
        if request.financial_intent == FinancialIntent.GOAL_PLANNING:
            return FinancialDomainOutcome(
                request_id=request.request_id,
                status="LIMITED",
                financial_intent=request.financial_intent,
                goal_impact=GoalImpact(
                    impact_level="NONE",
                    reasons=["未提供已确认投资目标，无法评估目标规划影响"],
                ),
                established_facts=[
                    DomainFact(
                        fact_id="goal-1",
                        statement="目标规划受限于缺少已确认目标",
                        source_refs=["profile:goals"],
                        directness="DIRECT",
                    )
                ],
                confidence=ConfidenceAssessment(
                    level="LOW",
                    reasons=["impact evidence: profile:goals"],
                    coverage_status="LIMITED",
                ),
                limitations=["缺少已确认投资目标"],
            )
        if request.requires_financial_snapshot:
            return FinancialDomainOutcome(
                request_id=request.request_id,
                status="LIMITED",
                financial_intent=request.financial_intent,
                suitability=SuitabilityAssessment(
                    rule_set_version="suitability-v0.pending-adr-004-approval",
                    rule_ids=["SUIT-RESEARCH-COVERAGE-001"],
                    evidence_refs=["obs-fixture"],
                    result="INSUFFICIENT_INFORMATION",
                    required_conditions=[
                        SuitabilityCondition(
                            condition_id=self.suitability_condition_id,
                            description=self.suitability_condition_description,
                            verification_source="ADR-004 approval record",
                        )
                    ],
                    reasons=["No personalized suitability determination is produced before ADR-004 approval"],
                    limitations=["ADR-004 rule thresholds and aggregation are not approved"],
                ),
                confidence=ConfidenceAssessment(
                    level="LOW",
                    reasons=["preflight"],
                    coverage_status="LIMITED",
                ),
                limitations=["ADR-004 rule thresholds and aggregation are not approved"],
            )
        return DomainOutcome(
            request_id=request.request_id,
            domain="finance",
            status="COMPLETE",
            established_facts=[
                DomainFact(
                    fact_id="quote-1",
                    statement="贵州茅台的受控行情研究已完成",
                    source_refs=["quote:600519"],
                    directness="DIRECT",
                )
            ],
            confidence=ConfidenceAssessment(level="HIGH", reasons=["validated"], coverage_status="COMPLETE"),
        )


def _app(
    dispatcher: FinanceDispatcher,
    store: InMemoryVerifiedEntityStore | None = None,
    *,
    knowledge_responder: object | None = None,
) -> CognitiveOrchestrator:
    entities = store or InMemoryVerifiedEntityStore()

    class _DefaultKnowledge:
        def answer(self, message: str) -> str:
            return f"skill-knowledge:{message}"

    return CognitiveOrchestrator(
        selector=FinanceCognitiveSelector(
            entities,
            knowledge_responder=knowledge_responder or _DefaultKnowledge(),
        ),
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
        understand=RuleBasedUnderstandModel(),
    )


@pytest.mark.asyncio
async def test_stock_research_action_dispatches_resolution_then_research() -> None:
    """LLM 输出 action={"tool": "stock-research", "parameters": {"symbol": "600519"}} 时，直接 dispatch 到研究流程。"""

    # 直接构造带 action 的 UnderstandOutput
    understood = UnderstandOutput(
        goals=[
            GoalSpec(
                goal_id="g1",
                objective="研究 600519",
                success_criteria=[SuccessCriterion(criterion_id="c1", description="获得研究结论")],
            )
        ],
        entities=UnderstandEntities(instruments=["600519"]),
        needs_external=True,
        action=ActionSpec(tool="stock-research", parameters={"symbol": "600519"}),
    )

    # 直接调用 selector 验证 action 路由
    selector = FinanceCognitiveSelector(InMemoryVerifiedEntityStore())
    action = await selector.select(_event("研究 600519"), understood=understood)

    assert action.action_type == CognitiveActionType.INVOKE_DOMAIN
    assert action.reason_code == "RESOLVE_INSTRUMENT"
    assert isinstance(action.domain_request, InstrumentResolutionRequest)
    assert action.domain_request.mention.normalized_text == "600519"


@pytest.mark.asyncio
async def test_portfolio_health_action_dispatches_impact_directly() -> None:
    """LLM 输出 action={"tool": "portfolio-health"} 时，直接 dispatch 到组合影响。"""

    understood = UnderstandOutput(
        goals=[
            GoalSpec(
                goal_id="g1",
                objective="评估组合风险",
                success_criteria=[SuccessCriterion(criterion_id="c1", description="获得组合暴露评估")],
            )
        ],
        needs_external=True,
        action=ActionSpec(tool="portfolio-health", parameters={}),
    )

    selector = FinanceCognitiveSelector(InMemoryVerifiedEntityStore())
    action = await selector.select(_event("我的组合风险怎么样"), understood=understood)

    assert action.action_type == CognitiveActionType.INVOKE_DOMAIN
    assert action.reason_code == "PORTFOLIO_IMPACT"
    assert isinstance(action.domain_request, FinancialDomainRequest)
    assert action.domain_request.financial_intent == FinancialIntent.PORTFOLIO_IMPACT


@pytest.mark.asyncio
async def test_suitability_action_dispatches_suitability_directly() -> None:
    """LLM 输出 action={"tool": "suitability-evaluation"} 时，直接 dispatch 到适配性评估。"""

    understood = UnderstandOutput(
        goals=[
            GoalSpec(
                goal_id="g1",
                objective="评估 600519 是否适合我",
                success_criteria=[SuccessCriterion(criterion_id="c1", description="获得适配性结论")],
            )
        ],
        entities=UnderstandEntities(instruments=["600519"]),
        needs_external=True,
        action=ActionSpec(tool="suitability-evaluation", parameters={"symbol": "600519"}),
    )

    selector = FinanceCognitiveSelector(InMemoryVerifiedEntityStore())
    action = await selector.select(_event("600519 适合我吗"), understood=understood)

    assert action.action_type == CognitiveActionType.INVOKE_DOMAIN
    assert action.reason_code == "SUITABILITY"
    assert isinstance(action.domain_request, FinancialDomainRequest)
    assert action.domain_request.financial_intent == FinancialIntent.SUITABILITY


@pytest.mark.asyncio
async def test_no_action_asks_user_for_tool_argument() -> None:
    """LLM 未输出 action 时，ASK_USER 要求补充参数。"""

    understood = UnderstandOutput(
        goals=[
            GoalSpec(
                goal_id="g1",
                objective="分析股票",
                success_criteria=[SuccessCriterion(criterion_id="c1", description="获得分析结论")],
            )
        ],
        needs_external=True,
        action=None,  # LLM 未选择工具
    )

    selector = FinanceCognitiveSelector(InMemoryVerifiedEntityStore())
    action = await selector.select(_event("分析股票"), understood=understood)

    assert action.action_type == CognitiveActionType.ASK_USER
    assert action.reason_code == "TOOL_ARGUMENT_REQUIRED"


@pytest.mark.asyncio
async def test_stock_research_without_symbol_asks_user() -> None:
    """LLM 输出 stock-research 但 parameters 缺少 symbol 时，ASK_USER 要求补充。"""

    understood = UnderstandOutput(
        goals=[
            GoalSpec(
                goal_id="g1",
                objective="研究股票",
                success_criteria=[SuccessCriterion(criterion_id="c1", description="获得研究结论")],
            )
        ],
        needs_external=True,
        action=ActionSpec(tool="stock-research", parameters={}),  # 缺少 symbol
    )

    selector = FinanceCognitiveSelector(InMemoryVerifiedEntityStore())
    action = await selector.select(_event("研究股票"), understood=understood)

    assert action.action_type == CognitiveActionType.ASK_USER
    assert action.reason_code == "TOOL_ARGUMENT_REQUIRED"


@pytest.mark.asyncio
async def test_instrument_conflict_asks_user() -> None:
    """LLM 参数中的 symbol 与 entities.instruments 不一致时，ASK_USER 确认。"""

    understood = UnderstandOutput(
        goals=[
            GoalSpec(
                goal_id="g1",
                objective="研究股票",
                success_criteria=[SuccessCriterion(criterion_id="c1", description="获得研究结论")],
            )
        ],
        entities=UnderstandEntities(instruments=["600519"]),  # entities 中是 600519
        needs_external=True,
        action=ActionSpec(tool="stock-research", parameters={"symbol": "000001"}),  # parameters 中是 000001
    )

    selector = FinanceCognitiveSelector(InMemoryVerifiedEntityStore())
    action = await selector.select(_event("研究股票"), understood=understood)

    assert action.action_type == CognitiveActionType.ASK_USER
    assert action.reason_code == "INSTRUMENT_CONFLICT"


@pytest.mark.asyncio
async def test_full_flow_stock_research_with_llm_action() -> None:
    """端到端：LLM 输出 action → dispatch → 领域返回 → 响应。"""

    dispatcher = FinanceDispatcher()
    app = _app(dispatcher)

    # 模拟 LLM 已输出 action（通过 RuleBasedUnderstandModel）
    result = await app.run(_event("600519 今天怎么样"))

    # 验证 dispatch 被调用
    assert len(dispatcher.requests) == 2  # resolve + research
    assert isinstance(dispatcher.requests[0], InstrumentResolutionRequest)
    assert isinstance(dispatcher.requests[1], FinancialDomainRequest)
    assert result.response.response_kind == "DOMAIN_RESULT"
    assert result.response.evidence_refs == ["quote:600519"]


@pytest.mark.asyncio
async def test_full_flow_portfolio_health_with_llm_action() -> None:
    """端到端：组合影响完整流程。"""

    dispatcher = FinanceDispatcher()
    app = _app(dispatcher)

    result = await app.run(
        _event("我的组合风险怎么样", enabled_skills=frozenset({"finance.portfolio-health"})),
    )

    assert len(dispatcher.requests) == 1
    request = dispatcher.requests[0]
    assert isinstance(request, FinancialDomainRequest)
    assert request.financial_intent == FinancialIntent.PORTFOLIO_IMPACT
    assert result.response.response_kind == "ANSWER"
    assert result.response.response_structure == "PORTFOLIO_IMPACT"


@pytest.mark.asyncio
async def test_full_flow_suitability_with_llm_action() -> None:
    """端到端：适配性评估完整流程。"""

    dispatcher = FinanceDispatcher()
    app = _app(dispatcher)

    result = await app.run(
        _event("600519 适合我吗", enabled_skills=frozenset({"finance.suitability-evaluation"})),
    )

    assert len(dispatcher.requests) == 1
    request = dispatcher.requests[0]
    assert isinstance(request, FinancialDomainRequest)
    assert request.financial_intent == FinancialIntent.SUITABILITY
    assert result.response.response_kind == "LIMITED"
    assert result.response.response_structure == "SUITABILITY"
