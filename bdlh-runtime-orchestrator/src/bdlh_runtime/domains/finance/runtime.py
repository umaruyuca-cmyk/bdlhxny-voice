"""M1 Finance Runtime 与 M2 研究结果双写：无 Checkpointer、无默认流量。"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from bdlh_runtime.contracts.analysis import AnalysisInput, AnalysisResult
from bdlh_runtime.contracts.data_requirements import DataRequirement
from bdlh_runtime.contracts.observation import Observation
from bdlh_runtime.domains.contracts import (
    ConfidenceAssessment,
    DomainError,
    DomainOperation,
)
from bdlh_runtime.observations.normalizer import ObservationNormalizer
from bdlh_runtime.runtimes.shared import assemble_analysis_input

from .authorization import ANALYSIS_CAPABILITY, FinanceCapabilityAuthorizationPolicy
from .contracts import (
    FinancialDomainOutcome,
    FinancialDomainRequest,
    FinancialIntent,
    InstrumentResolutionOutcome,
    InstrumentResolutionRequest,
    StockResearchResult,
)
from .instrument_resolver import FinanceInstrumentResolver
from .planner import FinancePlanner
from .research_builder import StockResearchResultBuilder
from .snapshot_builder import PORTFOLIO_VALUATION_CAPABILITY, USER_SNAPSHOT_CAPABILITIES
from .valuation_builder import PortfolioValuationBuilder, PortfolioValuationInput


ACTION_NOT_ENABLED = "ACTION_NOT_ENABLED"


class FinanceCapabilityExecutor(Protocol):
    """Finance Runtime 唯一的 Capability 执行边界。"""

    async def execute(
        self,
        capability: str,
        arguments: dict[str, Any],
        *,
        request_id: str,
    ) -> Observation | AnalysisResult: ...


class ApplicationFinanceCapabilityExecutor:
    """把稳定 Capability 分派给 MCP/Web/Java/本地分析 Adapter。"""

    def __init__(
        self,
        *,
        gateway_adapter: Any,
        web_search_adapter: Any,
        analysis_capability: Any,
        java_adapter: Any | None = None,
        valuation_builder: PortfolioValuationBuilder | None = None,
    ) -> None:
        self._gateway = gateway_adapter
        self._web_search = web_search_adapter
        self._analysis = analysis_capability
        self._java = java_adapter
        self._valuation_builder = valuation_builder or PortfolioValuationBuilder()
        self._normalizer = ObservationNormalizer()

    async def execute(
        self,
        capability: str,
        arguments: dict[str, Any],
        *,
        request_id: str,
    ) -> Observation | AnalysisResult:
        if capability == ANALYSIS_CAPABILITY:
            return self._analysis.analyze(AnalysisInput.model_validate(arguments))
        if capability == "research.web_search":
            observation = await self._web_search.execute(capability, arguments)
            return self._normalizer.normalize(observation)
        if capability in USER_SNAPSHOT_CAPABILITIES:
            if self._java is None:
                raise ValueError("Finance executor has no Java user-data adapter")
            return await self._java.execute(capability, arguments)
        if capability == PORTFOLIO_VALUATION_CAPABILITY:
            valuation_input = PortfolioValuationInput.model_validate(arguments)
            return self._valuation_builder.build(
                positions_observation=valuation_input.positions_observation,
                account_observation=valuation_input.account_observation,
                quote_observations=valuation_input.quote_observations,
                authenticated_user_id=valuation_input.authenticated_user_id,
            )
        if capability.startswith("market."):
            observation = await self._gateway.execute(
                capability,
                arguments,
                run_id=request_id,
            )
            return self._normalizer.normalize(observation)
        raise ValueError(f"Finance executor does not support capability: {capability}")


class FinanceRunState(BaseModel):
    """单次同步领域执行的短生命周期状态，不持久化。"""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    request: FinancialDomainRequest
    requirements: list[DataRequirement] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    tool_calls_used: int = 0
    analysis_input: AnalysisInput | None = None
    analysis_result: AnalysisResult | None = None
    stock_research_result: StockResearchResult | None = None
    limitations: list[str] = Field(default_factory=list)
    errors: list[DomainError] = Field(default_factory=list)


class FinanceRuntime:
    """执行五类单标的兼容股票研究，不产生聊天文案或持久副作用。"""

    def __init__(
        self,
        *,
        planner: FinancePlanner,
        authorization: FinanceCapabilityAuthorizationPolicy,
        executor: FinanceCapabilityExecutor,
        research_builder: StockResearchResultBuilder | None = None,
        instrument_resolver: FinanceInstrumentResolver | None = None,
    ) -> None:
        self._planner = planner
        self._authorization = authorization
        self._executor = executor
        self._research_builder = research_builder or StockResearchResultBuilder()
        self._instrument_resolver = instrument_resolver

    async def run(
        self, request: FinancialDomainRequest | InstrumentResolutionRequest
    ) -> FinancialDomainOutcome | InstrumentResolutionOutcome:
        if isinstance(request, InstrumentResolutionRequest):
            if self._instrument_resolver is None:
                return InstrumentResolutionOutcome(
                    request_id=request.request_id,
                    domain="finance",
                    status="LIMITED",
                    resolution_status="UNAVAILABLE",
                    confidence=ConfidenceAssessment(
                        level="LOW",
                        reasons=["Finance instrument resolver is not configured"],
                        coverage_status="LIMITED",
                    ),
                    errors=[DomainError(code="RESOLVER_NOT_CONFIGURED", message="Finance instrument resolver is not configured")],
                    limitations=["Finance instrument resolver is not configured"],
                )
            return await self._instrument_resolver.resolve(request)
        if request.financial_intent != FinancialIntent.STOCK_RESEARCH:
            return self._failed(
                request,
                ACTION_NOT_ENABLED,
                f"M1 does not enable financial intent {request.financial_intent}",
            )

        try:
            plan = self._planner.plan(request)
        except ValueError as exc:
            code = (
                "REQUESTED_TOPIC_NOT_ALLOWED"
                if "REQUESTED_TOPIC_NOT_ALLOWED" in str(exc)
                else "FINANCE_REQUEST_INVALID"
            )
            return self._failed(request, code, str(exc))

        decision = self._authorization.authorize(
            list(plan.data_requirements),
            request.authorized_operations,
        )
        missing_required = list(decision.missing_required)
        if not self._authorization.is_allowed(
            plan.analysis_capability,
            request.authorized_operations,
        ):
            missing_required.append(plan.analysis_capability)
        if missing_required:
            return self._failed(
                request,
                "REQUIRED_CAPABILITY_NOT_AUTHORIZED",
                "Required capabilities are not authorized: "
                + ", ".join(sorted(missing_required)),
            )

        state = FinanceRunState(
            request=request,
            requirements=list(plan.data_requirements),
            limitations=[
                f"Optional capability not authorized: {name}"
                for name in decision.skipped_optional
            ],
        )
        executable = list(decision.allowed_requirements)
        required_calls = sum(item.required for item in executable) + 1
        if required_calls > request.budget.tool_call_limit:
            return self._limited(
                request,
                "BUDGET_EXHAUSTED",
                "Tool call budget cannot cover required data and analysis capabilities",
            )

        remaining = request.budget.tool_call_limit - required_calls
        permitted: list[DataRequirement] = []
        for requirement in executable:
            if requirement.required:
                permitted.append(requirement)
            elif remaining > 0:
                permitted.append(requirement)
                remaining -= 1
            else:
                state.limitations.append(
                    f"Optional capability skipped by budget: {requirement.capability}"
                )

        try:
            async with asyncio.timeout(request.budget.runtime_seconds):
                for requirement in permitted:
                    result = await self._executor.execute(
                        requirement.capability,
                        requirement.arguments,
                        request_id=request.request_id,
                    )
                    if not isinstance(result, Observation):
                        return self._failed(
                            request,
                            "CAPABILITY_CONTRACT_VIOLATION",
                            f"{requirement.capability} did not return Observation",
                        )
                    if result.capability != requirement.capability:
                        return self._failed(
                            request,
                            "CAPABILITY_CONTRACT_VIOLATION",
                            "Capability response identity mismatch: "
                            f"expected {requirement.capability}, got {result.capability}",
                        )
                    state.observations.append(result)
                    state.tool_calls_used += 1

                state.analysis_input = assemble_analysis_input(
                    analysis_id=request.request_id,
                    symbol=request.instruments[0].symbol,
                    observations=state.observations,
                    requested_capabilities=[
                        item.capability for item in plan.data_requirements
                    ],
                    methodology_version="finance-research.m2",
                )
                analyzed = await self._executor.execute(
                    plan.analysis_capability,
                    state.analysis_input.model_dump(),
                    request_id=request.request_id,
                )
                state.tool_calls_used += 1
                if not isinstance(analyzed, AnalysisResult):
                    return self._failed(
                        request,
                        "CAPABILITY_CONTRACT_VIOLATION",
                        "analysis.run_analysis did not return AnalysisResult",
                    )
                state.analysis_result = analyzed
        except TimeoutError:
            return self._limited(
                request,
                "RUNTIME_BUDGET_EXHAUSTED",
                "Finance Runtime exceeded its runtime budget",
                retryable=True,
            )
        except Exception as exc:
            return self._failed(
                request,
                "FINANCE_EXECUTION_FAILED",
                f"Finance capability execution failed: {type(exc).__name__}",
                retryable=True,
            )

        return self._outcome(state)

    def _outcome(self, state: FinanceRunState) -> FinancialDomainOutcome:
        assert state.analysis_result is not None
        result = state.analysis_result
        errors = [
            DomainError(
                code=item.error_code or "CAPABILITY_UNAVAILABLE",
                message=item.error_message or f"{item.capability} is unavailable",
                retryable=True,
            )
            for item in state.observations
            if item.status in {"FAILED", "UNAVAILABLE"}
        ]
        if result.status == "FAILED":
            errors.append(
                DomainError(
                    code="ANALYSIS_FAILED",
                    message=(
                        result.limitations[0]
                        if result.limitations
                        else "analysis.run_analysis returned FAILED"
                    ),
                    retryable=False,
                )
            )

        try:
            research = self._research_builder.build(
                request=state.request,
                requirements=state.requirements,
                observations=state.observations,
                analysis_result=result,
                runtime_limitations=state.limitations,
            )
        except Exception:
            return self._failed(
                state.request,
                "STOCK_RESEARCH_BUILD_FAILED",
                "Stock research result could not be built from validated observations",
                analysis_result=result,
            )

        state.stock_research_result = research
        limitations = list(
            dict.fromkeys(
                state.limitations + result.limitations + research.limitations
            )
        )
        status = "FAILED" if result.status == "FAILED" else research.coverage
        return FinancialDomainOutcome(
            request_id=state.request.request_id,
            status=status,
            financial_intent=state.request.financial_intent,
            analysis_result=result,
            stock_research_result=research,
            confidence=research.confidence,
            limitations=limitations,
            errors=errors,
        )

    @staticmethod
    def _failed(
        request: FinancialDomainRequest,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        analysis_result: AnalysisResult | None = None,
    ) -> FinancialDomainOutcome:
        return FinancialDomainOutcome(
            request_id=request.request_id,
            status="FAILED",
            financial_intent=request.financial_intent,
            analysis_result=analysis_result,
            confidence=ConfidenceAssessment(
                level="LOW",
                reasons=[message],
                coverage_status="LIMITED",
            ),
            errors=[DomainError(code=code, message=message, retryable=retryable)],
            limitations=list(
                dict.fromkeys(
                    [message]
                    + (analysis_result.limitations if analysis_result else [])
                )
            ),
        )

    @staticmethod
    def _limited(
        request: FinancialDomainRequest,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> FinancialDomainOutcome:
        return FinancialDomainOutcome(
            request_id=request.request_id,
            status="LIMITED",
            financial_intent=request.financial_intent,
            confidence=ConfidenceAssessment(
                level="LOW",
                reasons=[message],
                coverage_status="LIMITED",
            ),
            errors=[DomainError(code=code, message=message, retryable=retryable)],
            limitations=[message],
        )


def create_finance_runtime(
    *,
    capability_registry: Any,
    gateway_adapter: Any,
    web_search_adapter: Any,
    analysis_capability: Any,
    java_adapter: Any | None = None,
) -> FinanceRuntime:
    """使用现有 Application 组件装配 M1 Runtime 与 M2 研究 Builder。"""

    planner = FinancePlanner(capability_registry)
    authorization = FinanceCapabilityAuthorizationPolicy(capability_registry)
    executor = ApplicationFinanceCapabilityExecutor(
        gateway_adapter=gateway_adapter,
        web_search_adapter=web_search_adapter,
        analysis_capability=analysis_capability,
        java_adapter=java_adapter,
    )
    return FinanceRuntime(
        planner=planner,
        authorization=authorization,
        executor=executor,
        research_builder=StockResearchResultBuilder(),
        instrument_resolver=FinanceInstrumentResolver(
            registry=capability_registry,
            authorization=authorization,
            executor=executor,
        ),
    )
