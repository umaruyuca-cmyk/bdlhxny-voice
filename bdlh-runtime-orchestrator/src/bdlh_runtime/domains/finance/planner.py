"""Finance Runtime 的确定性 Planner（研究面板 + requested_topics 驱动）。

基线研究面板固定；topics 只做附加扩展；``requires_financial_snapshot``
时追加用户事实能力。``PORTFOLIO_IMPACT`` / ``GOAL_PLANNING``（G8）走
组合健康面板，不跑完整研究基线，也不强制 ``analysis.run_analysis``。

G6：``web_research`` 在 Deep Research 已启用且调用策略触发时，优先规划
``research.deep_search``，否则保持 ``research.web_search``。
"""

from __future__ import annotations

from dataclasses import dataclass

from bdlh_runtime.contracts.data_requirements import DataRequirement
from bdlh_runtime.tools.deep_research.call_policy import evaluate_deep_research_trigger
from bdlh_runtime.tools.deep_research.contracts import DeepResearchRequest

from .authorization import ANALYSIS_CAPABILITY
from .contracts import FinancialDomainRequest, FinancialIntent

_QUOTE_CAPABILITY = "market.get_realtime_quote"
_RESOLVE_CAPABILITY = "market.resolve_instrument"
_WEB_SEARCH = "research.web_search"
_DEEP_SEARCH = "research.deep_search"

#: STOCK_RESEARCH 基线研究面板（域内确定性组装，不随问话体裁变化）
_BASELINE_RESEARCH_CAPABILITIES = (
    _RESOLVE_CAPABILITY,
    _QUOTE_CAPABILITY,
    "market.get_historical_prices",
    "market.get_financial_statements",
    "market.get_valuation",
    "market.get_industry_context",
    "market.get_news",
)

#: 用户事实能力（Suitability / portfolio-health / goal-planning）
_SNAPSHOT_CAPABILITIES = (
    "portfolio.get_current_positions",
    "portfolio.get_account_snapshot",
    "user.get_risk_profile",
)

_IMPACT_INTENTS = frozenset({FinancialIntent.PORTFOLIO_IMPACT, FinancialIntent.GOAL_PLANNING})


@dataclass(frozen=True)
class FinancePlan:
    """数据需求和可选确定性分析步骤组成的不可变计划。"""

    data_requirements: tuple[DataRequirement, ...]
    analysis_capability: str | None = ANALYSIS_CAPABILITY

    @property
    def capabilities(self) -> tuple[str, ...]:
        caps = tuple(item.capability for item in self.data_requirements)
        if self.analysis_capability:
            return caps + (self.analysis_capability,)
        return caps


class FinancePlanner:
    """从显式请求字段（topics + instruments + intent）生成数据需求。

    topic→能力对照来自库表（经 RegistrySnapshot 派生注入），仅用于附加扩展；
    基线面板不依赖 topics。
    """

    def __init__(
        self,
        topic_capabilities: dict[str, list[str]] | None = None,
        *,
        deep_research_enabled: bool = False,
    ) -> None:
        self._topic_capabilities = topic_capabilities or {}
        self._deep_research_enabled = deep_research_enabled

    def plan(self, request: FinancialDomainRequest) -> FinancePlan:
        if request.financial_intent in _IMPACT_INTENTS:
            return self._plan_impact(request)

        baseline: list[str] = []
        for _instrument in request.instruments:
            baseline.extend(_BASELINE_RESEARCH_CAPABILITIES)
        optional: list[str] = []
        for topic in sorted(request.requested_topics):
            for capability in self._topic_capabilities.get(topic, []):
                if capability not in baseline and capability not in optional:
                    optional.append(capability)
        if request.requires_financial_snapshot:
            baseline.extend(_SNAPSHOT_CAPABILITIES)

        optional = self._maybe_prefer_deep_search(request, optional)

        requirements = tuple(
            DataRequirement(
                requirement_id=f"cap-{index}-{name.replace('.', '-')}",
                capability=name,
                required=name in baseline,
                reason="Finance research panel" if name in baseline else f"Requested topic attachment: {name}",
                arguments=self._arguments(name, request),
            )
            for index, name in enumerate(dict.fromkeys(baseline + optional))
        )
        return FinancePlan(data_requirements=requirements)

    def _plan_impact(self, request: FinancialDomainRequest) -> FinancePlan:
        """组合健康 / 目标规划：只读用户事实面板，估值由 Runtime 追加。"""
        requirements = tuple(
            DataRequirement(
                requirement_id=f"cap-{index}-{name.replace('.', '-')}",
                capability=name,
                required=True,
                reason="Finance portfolio-health panel",
                arguments=self._arguments(name, request),
            )
            for index, name in enumerate(_SNAPSHOT_CAPABILITIES)
        )
        return FinancePlan(data_requirements=requirements, analysis_capability=None)

    def _maybe_prefer_deep_search(
        self,
        request: FinancialDomainRequest,
        optional: list[str],
    ) -> list[str]:
        """复杂 web_research 在门禁满足时升档到 deep_search（不静默改 web_search Schema）。"""
        if not self._deep_research_enabled:
            return optional
        if "web_research" not in request.requested_topics and _WEB_SEARCH not in optional:
            return optional
        symbol = request.instruments[0].symbol if request.instruments else ""
        probe = DeepResearchRequest(
            request_id=request.request_id,
            question=request.objective,
            objective=request.objective,
            research_topics=sorted(request.requested_topics),
            success_criteria=[request.objective] if request.objective.strip() else [],
        )
        decision = evaluate_deep_research_trigger(
            probe,
            feature_enabled=True,
            in_allowed=True,
            entitled=True,
            sync_budget_ok=True,
            user_text=f"{request.objective}\n{symbol}",
        )
        if not decision.should_deep:
            return optional
        upgraded = [item for item in optional if item != _WEB_SEARCH]
        if _DEEP_SEARCH not in upgraded and _DEEP_SEARCH not in _BASELINE_RESEARCH_CAPABILITIES:
            upgraded.append(_DEEP_SEARCH)
        return upgraded

    @staticmethod
    def _arguments(name: str, request: FinancialDomainRequest) -> dict:
        if name in (_QUOTE_CAPABILITY, _RESOLVE_CAPABILITY):
            return {"symbol": request.instruments[0].symbol}
        if name == "market.get_historical_prices":
            return {"symbol": request.instruments[0].symbol, "lookback_days": 120}
        if name.startswith("market."):
            return {"symbol": request.instruments[0].symbol}
        if name == _WEB_SEARCH:
            return {"query": f"{request.instruments[0].symbol} 最新动态", "mode": "NEWS", "max_results": 5}
        if name == _DEEP_SEARCH:
            symbol = request.instruments[0].symbol
            return {
                "request_id": request.request_id,
                "question": request.objective,
                "objective": request.objective,
                "research_topics": sorted(request.requested_topics) or ["web_research"],
                "success_criteria": [
                    f"覆盖标的 {symbol} 的公开研究证据",
                    "给出带引用的综合结论要点",
                ],
            }
        if name in _SNAPSHOT_CAPABILITIES:
            return {"user_id": request.authenticated_user_id}
        return {}
