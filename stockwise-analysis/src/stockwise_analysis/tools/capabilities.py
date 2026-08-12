"""统一业务能力目录。

实施标记：``SW31-TOOLSET-VIEW``。Capability 规格仍是唯一能力真源；
Toolset 只读取每个规格声明的业务分组，不复制底层路由定义。

目录只描述 Agent 可以理解的稳定业务能力，不暴露 MCP 服务名、原始工具名、
传输协议或供应商参数。底层路由仍由 integrations/mcp 负责。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


CapabilityDomain = Literal[
    "market",
    "fundamental",
    "sector",
    "research",
    "portfolio",
    "user",
    "analysis",
]
CapabilityAdapter = Literal["mcp", "java", "web", "local"]


class ToolsetName(StrEnum):
    """暴露给上层规划器的稳定业务能力分组。"""

    MARKET_READ = "market_read"
    FUNDAMENTAL_READ = "fundamental_read"
    NEWS_READ = "news_read"
    PORTFOLIO_READ = "portfolio_read"
    FINANCIAL_PROFILE_READ = "financial_profile_read"
    PLANNING_COMPUTE = "planning_compute"


@dataclass(frozen=True)
class CapabilitySpec:
    """一个可暴露给规划器的统一只读能力。"""

    name: str
    description: str
    domain: CapabilityDomain
    adapter: CapabilityAdapter
    analysis_types: frozenset[str]
    required_arguments: frozenset[str] = frozenset()
    output_schema: str = "Observation"
    timeout_seconds: int = 20
    cost: int = 1
    read_only: bool = True
    toolsets: frozenset[ToolsetName] = frozenset()

    def manifest(self) -> dict[str, object]:
        """返回可安全放入模型上下文的描述；不包含底层路由细节。"""

        return {
            "name": self.name,
            "description": self.description,
            "domain": self.domain,
            "required_arguments": sorted(self.required_arguments),
            "output_schema": self.output_schema,
            "read_only": self.read_only,
            "toolsets": sorted(item.value for item in self.toolsets),
        }


class CapabilityRegistry:
    """全局统一能力白名单。"""

    def __init__(self) -> None:
        self._items: dict[str, CapabilitySpec] = {}

    def register(self, spec: CapabilitySpec) -> None:
        if spec.name in self._items:
            raise ValueError(f"Capability already registered: {spec.name}")
        if not spec.read_only:
            raise ValueError("Only read-only capabilities may be exposed to research agents")
        self._items[spec.name] = spec

    def get(self, name: str) -> CapabilitySpec:
        try:
            return self._items[name]
        except KeyError as exc:
            raise KeyError(f"Capability is not registered: {name}") from exc

    def contains(self, name: str) -> bool:
        return name in self._items

    def list(self) -> list[CapabilitySpec]:
        return [self._items[name] for name in sorted(self._items)]

    def candidates_for(self, analysis_type: str) -> list[CapabilitySpec]:
        """按分析类型生成候选集，避免每轮向模型暴露全部能力。"""

        return [
            spec
            for spec in self.list()
            if analysis_type in spec.analysis_types
        ]


def build_default_capability_registry() -> CapabilityRegistry:
    """创建当前生产代码支持的统一能力目录。"""

    registry = CapabilityRegistry()
    market_types = frozenset({
        "market_snapshot", "technical", "fundamental", "valuation",
        "portfolio_impact", "comprehensive",
    })

    specs = [
        CapabilitySpec(
            "market.resolve_instrument",
            "解析证券代码或名称并返回标准化标的信息",
            "market", "mcp", market_types,
            frozenset({"symbol"}), "InstrumentObservation",
            toolsets=frozenset({ToolsetName.MARKET_READ}),
        ),
        CapabilitySpec(
            "market.get_realtime_quote",
            "获取指定标的的最新标准化行情",
            "market", "mcp", market_types,
            frozenset({"symbol"}), "RealtimeQuoteObservation",
            toolsets=frozenset({ToolsetName.MARKET_READ}),
        ),
        CapabilitySpec(
            "market.get_historical_prices",
            "获取指定标的的标准化历史 OHLCV 数据",
            "market", "mcp", frozenset({"technical", "portfolio_impact", "comprehensive"}),
            frozenset({"symbol", "lookback_days"}), "HistoricalPriceObservation",
            toolsets=frozenset({ToolsetName.MARKET_READ}),
        ),
        CapabilitySpec(
            "market.get_financial_statements",
            "获取基本面分析所需的标准化财务报表数据",
            "fundamental", "mcp", frozenset({"fundamental", "valuation", "comprehensive"}),
            frozenset({"symbol"}), "FinancialStatementsObservation",
            toolsets=frozenset({ToolsetName.FUNDAMENTAL_READ}),
        ),
        CapabilitySpec(
            "market.get_valuation",
            "获取市盈率、市净率等标准化估值数据",
            "fundamental", "mcp", frozenset({"fundamental", "valuation", "comprehensive"}),
            frozenset({"symbol"}), "ValuationObservation",
            toolsets=frozenset({ToolsetName.FUNDAMENTAL_READ}),
        ),
        CapabilitySpec(
            "market.get_industry_context",
            "获取标的所属行业及行业背景",
            "sector", "mcp", frozenset({"fundamental", "valuation", "comprehensive"}),
            frozenset({"symbol"}), "IndustryObservation",
            toolsets=frozenset({ToolsetName.FUNDAMENTAL_READ}),
        ),
        CapabilitySpec(
            "market.get_money_flow",
            "获取标的资金流数据",
            "market", "mcp", frozenset({"technical", "comprehensive"}),
            frozenset({"symbol"}), "MoneyFlowObservation",
            toolsets=frozenset({ToolsetName.MARKET_READ}),
        ),
        CapabilitySpec(
            "market.get_news",
            "获取与标的相关的结构化新闻",
            "research", "mcp", frozenset({"technical", "fundamental", "valuation", "comprehensive"}),
            frozenset({"symbol"}), "NewsObservation",
            toolsets=frozenset({ToolsetName.NEWS_READ}),
        ),
        CapabilitySpec(
            "portfolio.get_current_positions",
            "读取当前用户持仓",
            "portfolio", "java", frozenset({"portfolio_impact", "comprehensive"}),
            output_schema="PortfolioObservation", timeout_seconds=10,
            toolsets=frozenset({ToolsetName.PORTFOLIO_READ}),
        ),
        CapabilitySpec(
            "portfolio.get_account_snapshot",
            "读取当前用户账户快照",
            "portfolio", "java", frozenset({"portfolio_impact", "comprehensive"}),
            output_schema="AccountObservation", timeout_seconds=10,
            toolsets=frozenset({ToolsetName.PORTFOLIO_READ}),
        ),
        CapabilitySpec(
            "portfolio.get_transaction_history",
            "读取当前用户交易历史",
            "portfolio", "java", frozenset({"portfolio_impact", "comprehensive"}),
            output_schema="TransactionObservation", timeout_seconds=10,
            toolsets=frozenset({ToolsetName.PORTFOLIO_READ}),
        ),
        CapabilitySpec(
            "user.get_risk_profile",
            "读取当前用户风险画像",
            "user", "java", frozenset({"portfolio_impact", "comprehensive"}),
            output_schema="RiskProfileObservation", timeout_seconds=10,
            toolsets=frozenset({ToolsetName.FINANCIAL_PROFILE_READ}),
        ),
        CapabilitySpec(
            "research.web_search",
            "检索最新外部资料并返回带来源的标准化结果",
            "research", "web", frozenset({"fundamental", "valuation", "comprehensive"}),
            frozenset({"query"}), "WebSearchObservation",
            toolsets=frozenset({ToolsetName.NEWS_READ}),
        ),
        CapabilitySpec(
            "analysis.run_analysis",
            "对已标准化的数据执行确定性金融分析",
            "analysis", "local", market_types,
            output_schema="AnalysisResult", timeout_seconds=60,
            toolsets=frozenset({ToolsetName.PLANNING_COMPUTE}),
        ),
    ]
    for spec in specs:
        registry.register(spec)
    return registry
