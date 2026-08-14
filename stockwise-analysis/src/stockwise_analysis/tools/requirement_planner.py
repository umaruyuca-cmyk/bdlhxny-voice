"""分析类型到统一能力需求的确定性规划。

核心数据由规则保证，LLM 不负责决定是否获取关键行情或财报；可选能力按用户
明确提及的主题加入，综合分析则使用完整候选集。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stockwise_analysis.contracts.data_requirements import DataRequirement

from .capabilities import CapabilityRegistry


@dataclass(frozen=True)
class RequirementPolicy:
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()


REQUIREMENT_POLICIES: dict[str, RequirementPolicy] = {
    "market_snapshot": RequirementPolicy(
        required=("market.get_realtime_quote",),
    ),
    "technical": RequirementPolicy(
        required=("market.get_realtime_quote", "market.get_historical_prices"),
        optional=("market.get_money_flow", "market.get_news"),
    ),
    "fundamental": RequirementPolicy(
        required=("market.get_realtime_quote", "market.get_financial_statements"),
        optional=("market.get_valuation", "market.get_industry_context", "market.get_news", "research.web_search"),
    ),
    "valuation": RequirementPolicy(
        required=("market.get_realtime_quote", "market.get_valuation"),
        optional=("market.get_financial_statements", "market.get_industry_context", "market.get_news", "research.web_search"),
    ),
    "portfolio_impact": RequirementPolicy(
        required=("market.get_realtime_quote", "market.get_historical_prices"),
    ),
    "comprehensive": RequirementPolicy(
        required=(
            "market.get_realtime_quote",
            "market.get_historical_prices",
            "market.get_financial_statements",
            "market.get_valuation",
        ),
        optional=(
            "market.get_industry_context",
            "market.get_money_flow",
            "market.get_news",
            "research.web_search",
        ),
    ),
}


_OPTIONAL_TRIGGERS: dict[str, tuple[str, ...]] = {
    "market.get_money_flow": ("资金", "主力", "流入", "流出"),
    "market.get_news": ("新闻", "消息", "事件", "舆情", "公告"),
    "market.get_valuation": ("估值", "市盈率", "市净率", "PE", "PB"),
    "market.get_industry_context": ("行业", "板块", "赛道", "同业"),
    "market.get_financial_statements": ("财务", "财报", "利润", "现金流", "负债"),
    "research.web_search": ("最新", "新闻", "消息", "事件", "政策", "舆情"),
}

REQUESTED_TOPIC_CAPABILITIES: dict[str, str] = {
    "news": "market.get_news",
    "money_flow": "market.get_money_flow",
    "industry": "market.get_industry_context",
    "web_research": "research.web_search",
}


class CapabilityRequirementPlanner:
    """从受控策略生成本轮需求和候选能力。"""

    def __init__(self, registry: CapabilityRegistry):
        self._registry = registry

    def plan(self, intent: dict[str, Any], request: dict[str, Any]) -> list[DataRequirement]:
        analysis_type = str(intent.get("analysis_type") or "market_snapshot")
        policy = REQUIREMENT_POLICIES.get(analysis_type, REQUIREMENT_POLICIES["market_snapshot"])
        message = str(request.get("message", ""))

        selected = list(policy.required)
        for capability in policy.optional:
            if analysis_type == "comprehensive" or self._is_requested(capability, message):
                selected.append(capability)

        return self._build_requirements(selected, policy, intent, request)

    def plan_explicit(
        self,
        *,
        analysis_type: str,
        symbol: str,
        requested_topics: set[str] | frozenset[str] = frozenset(),
    ) -> list[DataRequirement]:
        """为 Finance Runtime 生成不依赖自由文本关键词的确定性计划。"""

        try:
            policy = REQUIREMENT_POLICIES[analysis_type]
        except KeyError as exc:
            raise ValueError(f"Unsupported analysis_type: {analysis_type}") from exc

        selected = list(policy.required)
        if analysis_type == "comprehensive":
            selected.extend(policy.optional)
        else:
            for topic in sorted(requested_topics):
                try:
                    capability = REQUESTED_TOPIC_CAPABILITIES[topic]
                except KeyError as exc:
                    raise ValueError(f"Unsupported requested_topic: {topic}") from exc
                if capability not in policy.optional:
                    raise ValueError(
                        f"REQUESTED_TOPIC_NOT_ALLOWED: {topic} is not available for {analysis_type}"
                    )
                selected.append(capability)

        intent = {"analysis_type": analysis_type, "symbol": symbol}
        request = {"symbol": symbol}
        return self._build_requirements(selected, policy, intent, request)

    def _build_requirements(
        self,
        selected: list[str],
        policy: RequirementPolicy,
        intent: dict[str, Any],
        request: dict[str, Any],
    ) -> list[DataRequirement]:
        requirements: list[DataRequirement] = []
        for index, capability in enumerate(dict.fromkeys(selected)):
            if not self._registry.contains(capability):
                raise ValueError(f"Requirement policy references unregistered capability: {capability}")
            requirements.append(
                DataRequirement(
                    requirement_id=f"cap-{index + 1}-{capability.replace('.', '-')}",
                    capability=capability,
                    required=capability in policy.required,
                    reason=self._reason(capability),
                    arguments=self._arguments(capability, intent, request),
                )
            )
        return requirements

    def candidate_manifest(self, analysis_type: str) -> list[dict[str, object]]:
        """返回当前分析类型可能使用的安全候选集，而不是全部原始工具。"""

        policy = REQUIREMENT_POLICIES.get(analysis_type, REQUIREMENT_POLICIES["market_snapshot"])
        allowed = set(policy.required) | set(policy.optional)
        return [
            spec.manifest()
            for spec in self._registry.candidates_for(analysis_type)
            if spec.name in allowed
        ]

    @staticmethod
    def _is_requested(capability: str, message: str) -> bool:
        return any(keyword in message for keyword in _OPTIONAL_TRIGGERS.get(capability, ()))

    @staticmethod
    def _arguments(capability: str, intent: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        symbol = intent.get("symbol") or request.get("symbol")
        if capability == "market.get_historical_prices":
            return {"symbol": symbol, "lookback_days": 120}
        if capability == "research.web_search":
            topic = symbol or intent.get("scope") or "A股市场"
            return {"query": f"{topic} 最新动态", "mode": "NEWS", "max_results": 5}
        if capability.startswith("market."):
            return {"symbol": symbol}
        return {}

    @staticmethod
    def _reason(capability: str) -> str:
        reasons = {
            "market.get_realtime_quote": "获取当前市场数据",
            "market.get_historical_prices": "计算技术指标需要历史价格",
            "market.get_financial_statements": "基本面分析需要财务数据",
            "market.get_valuation": "估值分析需要估值数据",
            "market.get_industry_context": "补充行业和同业背景",
            "market.get_money_flow": "补充资金流证据",
            "market.get_news": "补充标的相关新闻",
            "research.web_search": "补充带来源的最新外部证据",
        }
        return reasons.get(capability, f"获取 {capability} 数据")
