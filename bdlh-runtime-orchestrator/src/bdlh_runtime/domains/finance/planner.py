"""Finance Runtime 的确定性 Planner（重写：研究面板 + requested_topics 驱动）。

不再按类型桶裁菜单；STOCK_RESEARCH 产统一基线研究面板
（resolve/quote/historical/financial/valuation/industry/news），
topics 只做附加扩展，SUITABILITY 追加用户事实能力。
预算（tool_call_limit）控制上限，数据计划不随问话体裁变化。
"""

from __future__ import annotations

from dataclasses import dataclass

from bdlh_runtime.contracts.data_requirements import DataRequirement

from .authorization import ANALYSIS_CAPABILITY
from .contracts import FinancialDomainRequest, FinancialIntent

_QUOTE_CAPABILITY = "market.get_realtime_quote"
_RESOLVE_CAPABILITY = "market.resolve_instrument"

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

#: SUITABILITY 追加的用户事实能力（requires_financial_snapshot 时同样追加）
_SNAPSHOT_CAPABILITIES = (
    "portfolio.get_current_positions",
    "portfolio.get_account_snapshot",
    "user.get_risk_profile",
)


@dataclass(frozen=True)
class FinancePlan:
    """数据需求和必需确定性分析步骤组成的不可变计划。"""

    data_requirements: tuple[DataRequirement, ...]
    analysis_capability: str = ANALYSIS_CAPABILITY

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(item.capability for item in self.data_requirements) + (
            self.analysis_capability,
        )


class FinancePlanner:
    """从显式请求字段（topics + instruments + intent）生成数据需求。

    topic→能力对照来自库表（经 RegistrySnapshot 派生注入），仅用于附加扩展；
    基线面板不依赖 topics。
    """

    def __init__(self, topic_capabilities: dict[str, list[str]] | None = None) -> None:
        self._topic_capabilities = topic_capabilities or {}

    def plan(self, request: FinancialDomainRequest) -> FinancePlan:
        baseline: list[str] = []
        for _instrument in request.instruments:
            baseline.extend(_BASELINE_RESEARCH_CAPABILITIES)
        optional: list[str] = []
        for topic in sorted(request.requested_topics):
            for capability in self._topic_capabilities.get(topic, []):
                if capability not in baseline and capability not in optional:
                    optional.append(capability)
        if (request.financial_intent == FinancialIntent.SUITABILITY
                or request.requires_financial_snapshot):
            baseline.extend(_SNAPSHOT_CAPABILITIES)
        if (request.financial_intent == FinancialIntent.SUITABILITY
                or request.requires_financial_snapshot):
            names.extend(_SNAPSHOT_CAPABILITIES)

        requirements = tuple(
            DataRequirement(
                requirement_id=f"cap-{index}-{name.replace('.', '-')}",
                capability=name,
                required=name in baseline,
                reason="Finance research panel"
                if name in baseline
                else f"Requested topic attachment: {name}",
                arguments=self._arguments(name, request),
            )
            for index, name in enumerate(dict.fromkeys(baseline + optional))
        )
        return FinancePlan(data_requirements=requirements)

    @staticmethod
    def _arguments(name: str, request: FinancialDomainRequest) -> dict:
        if name == _QUOTE_CAPABILITY or name == _RESOLVE_CAPABILITY:
            return {"symbol": request.instruments[0].symbol}
        if name == "market.get_historical_prices":
            return {"symbol": request.instruments[0].symbol, "lookback_days": 120}
        if name.startswith("market."):
            return {"symbol": request.instruments[0].symbol}
        if name == "research.web_search":
            return {"query": f"{request.instruments[0].symbol} 最新动态", "mode": "NEWS", "max_results": 5}
        return {}
