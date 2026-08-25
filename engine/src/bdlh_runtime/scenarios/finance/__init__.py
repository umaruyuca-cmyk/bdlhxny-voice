"""金融场景包:显式启用后才注入工具场景映射、危险动作词表与出口护栏。

启用: ``SCENARIO_PACKS=finance`` 或 ``enable_scenario_pack("finance")``。
"""

from __future__ import annotations

import re

from bdlh_runtime.scenarios import register_description_overlays, register_pack
from bdlh_runtime.scenarios.dangerous_actions import DangerousActionProfile, register_profile

PACK_ID = "finance"

FINANCE_SCENE_TOOLSETS: dict[str, frozenset[str]] = {
    "market": frozenset({"market_read", "fundamental_read", "news_read"}),
    "portfolio": frozenset({"portfolio_read", "financial_profile_read", "planning_compute"}),
    "research": frozenset({"market_read", "fundamental_read", "news_read", "planning_compute"}),
    "watch": frozenset({"market_read", "portfolio_read", "financial_profile_read"}),
}

_FINANCE_TOOLSETS_UNION = frozenset().union(*FINANCE_SCENE_TOOLSETS.values())

FINANCE_TRADING_PROFILE = DangerousActionProfile(
    profile_id="finance-trading-v1",
    en_pattern=re.compile(
        r"\b(buy|sell|purchase|trade|trading|order|place_order|execute_order)\b",
        re.IGNORECASE,
    ),
    zh_terms=("买入", "卖出", "下单", "挂单", "撤单", "交易执行", "调仓执行"),
    exempt_names=frozenset(
        {
            "portfolio.get_transaction_history",
            "order.get_status",
        }
    ),
)

FINANCE_DESCRIPTION_OVERLAYS: dict[str, str] = {
    "market.resolve_instrument": (
        "把用户说的证券名、简称或代码解析成标准标的（代码、名称、市场）。"
        "用于「某标的是哪个代码」。检索关键词：证券代码、标的解析。"
    ),
    "market.get_realtime_quote": (
        "查询一只证券的最新公开报价（最新价、涨跌幅、成交额）。"
        "用于「现在什么价」。检索关键词：实时报价、最新价、涨跌。"
    ),
    "market.get_historical_prices": (
        "查询一只证券的历史 OHLCV 价格序列。"
        "用于「近一年走势」。检索关键词：历史价格、K线、OHLCV。"
    ),
    "market.get_financial_statements": (
        "查询一只证券的标准化财务报表。"
        "用于「营收多少」。检索关键词：财报、三大报表。"
    ),
    "market.get_valuation": (
        "查询一只证券的估值指标。"
        "用于「估值高不高」。检索关键词：估值、市盈率、市净率。"
    ),
    "market.get_industry_context": (
        "查询标的所属行业与行业背景。检索关键词：行业、板块。"
    ),
    "market.get_money_flow": (
        "查询标的资金流向摘要。检索关键词：资金流。"
    ),
    "market.get_news": (
        "查询标的结构化新闻。检索关键词：新闻、资讯。"
    ),
    "research.web_search": (
        "检索外部公开资料并带来源返回。检索关键词：公开检索、网页来源。"
    ),
    "research.deep_search": (
        "对公开资料做多步交叉核验并带回证据链。检索关键词：深度研究、证据链。"
    ),
    "analysis.run_analysis": (
        "对已标准化的结构化数据执行确定性分析，返回类型化结果。"
        "检索关键词：分析引擎、诊断、评分。"
    ),
    "portfolio.get_current_positions": (
        "读取当前登录用户的持仓列表（需登录）。检索关键词：持仓、仓位。"
    ),
    "portfolio.get_account_snapshot": (
        "读取当前登录用户的账户快照（需登录）。检索关键词：账户、现金、资产。"
    ),
    "portfolio.get_transaction_history": (
        "读取已发生交易的历史记录（只读，需登录）。检索关键词：成交历史。"
    ),
    "portfolio.build_current_valuation": (
        "基于最新报价对当前持仓做确定性估值重算（需登录）。检索关键词：估值重算。"
    ),
    "user.get_risk_profile": (
        "读取当前登录用户的风险画像（需登录）。检索关键词：风险画像、风险偏好。"
    ),
}

_OUTPUT_KEYWORDS_C1 = (
    "买入",
    "卖出",
    "下单",
    "转账",
    "建议购买",
    "立刻买入",
    "清仓",
    "建仓",
    "加仓",
    "减仓",
    "委托买入",
    "委托卖出",
    "帮我买",
    "帮我卖",
)

_OUTPUT_KEYWORDS_C2 = (
    "适合您",
    "推荐持有",
    "建议配置",
    "该标的适合",
    "适合投资",
    "推荐买入",
    "建议买入",
    "符合您的风险",
    "适合你的风险",
)


def _load() -> None:
    from bdlh_runtime.engine import loader as tool_loader
    from bdlh_runtime.engine.output_guardrail import (
        KeywordBlockCheck,
        append_default_output_check,
        set_live_compliance_keywords,
    )
    from bdlh_runtime.tools.catalog import (
        EmptyArgs,
        HistoricalPricesArgs,
        SymbolArgs,
        ValuationInputsArgs,
        register_param_models,
    )

    register_profile(FINANCE_TRADING_PROFILE)
    register_description_overlays(PACK_ID, FINANCE_DESCRIPTION_OVERLAYS)
    register_param_models(
        {
            "market.resolve_instrument": SymbolArgs,
            "market.get_realtime_quote": SymbolArgs,
            "market.get_historical_prices": HistoricalPricesArgs,
            "market.get_financial_statements": SymbolArgs,
            "market.get_valuation": SymbolArgs,
            "market.get_industry_context": SymbolArgs,
            "market.get_money_flow": SymbolArgs,
            "market.get_news": SymbolArgs,
            "portfolio.get_current_positions": EmptyArgs,
            "portfolio.get_account_snapshot": EmptyArgs,
            "portfolio.get_transaction_history": EmptyArgs,
            "portfolio.build_current_valuation": ValuationInputsArgs,
            "user.get_risk_profile": EmptyArgs,
        }
    )
    tool_loader.register_scene_toolsets(FINANCE_SCENE_TOOLSETS)
    tool_loader.extend_core_scene("general", _FINANCE_TOOLSETS_UNION)
    tool_loader.set_wide_pack_scene("research")
    set_live_compliance_keywords(
        c1=_OUTPUT_KEYWORDS_C1,
        c2=_OUTPUT_KEYWORDS_C2,
        c2_footer="\n\n本结果仅为筛查草稿，不构成投资建议。",
    )
    append_default_output_check(
        KeywordBlockCheck(
            check_name="C1_VIOLATION",
            keywords=_OUTPUT_KEYWORDS_C1,
            fixed_fragment="（该操作不被允许）",
            detail_prefix="含危险执行语义",
        )
    )
    append_default_output_check(
        KeywordBlockCheck(
            check_name="C2_VIOLATION",
            keywords=_OUTPUT_KEYWORDS_C2,
            fixed_fragment="（不构成适当性结论）",
            detail_prefix="含不当确定性结论",
            footer="\n\n本结果仅为筛查草稿，不构成投资建议。",
        )
    )


register_pack(PACK_ID, _load)
