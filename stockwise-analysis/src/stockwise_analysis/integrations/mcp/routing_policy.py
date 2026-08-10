"""市场统一能力的主备路由策略（2026-08-06 实测校准版）。

路由表基于云端实测验证（见架构文档 v3.1 §9.0），核心结论：
- eastmoney 系 source（push2 域名）在云端仍被风控；
- akshare-one 的 source=xueqiu（实时行情）和 source=sina（历史K线）可用，
  构成真正的异构备份，无需外接第三方；
- 两个 MCP 参数 schema 不同（interval vs period），路由层负责翻译。

本模块定义"统一能力 → MCP + 原始工具 + source + 参数翻译"的完整路由规则。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RouteTarget:
    """一个路由目标：哪个 MCP 的哪个工具，带什么 source 参数。

    source 仅 akshare-one 的行情类工具使用（xueqiu/sina），cn-financial
    的工具不接 source 参数（它内部自己降级）。
    """

    mcp: str               # "cn-financial-mcp" 或 "akshare-one-mcp"
    tool: str              # 原始工具名，如 get_realtime_quote
    source: str | None = None  # akshare-one 的数据源选择（xueqiu/sina/eastmoney）


@dataclass(frozen=True)
class RoutePolicy:
    """一个统一能力的路由策略：首选 + 备选。

    备选在首选失败时触发。由于两个 MCP 同源，备选可能是同一 MCP 的不同
    source（如实时行情首选 akshare-one:xueqiu，备选 cn-financial 默认源）。
    """

    capability: str
    primary: RouteTarget
    fallback: RouteTarget | None = None
    # 参数翻译规则：统一能力参数 → 原始工具参数
    param_map: dict[str, str] = field(default_factory=dict)


# ── 实测校准路由表（架构文档 v3.1 §9.1）──
# 推导逻辑：
# - 实时行情：akshare-one eastmoney 被风控，xueqiu 0.6s 可用 → 首选 xueqiu
# - 历史K线：cn-financial 默认源 0.8s 可用 → 首选；akshare-one sina 备选
# - 财报：两者走 datacenter 稳定，cn-financial 字段更全（中文亿元）
DEFAULT_ROUTES: dict[str, RoutePolicy] = {
    "market.resolve_instrument": RoutePolicy(
        capability="market.resolve_instrument",
        primary=RouteTarget(mcp="cn-financial-mcp", tool="search_stock"),
    ),
    "market.get_realtime_quote": RoutePolicy(
        capability="market.get_realtime_quote",
        # eastmoney 系被风控，xueqiu 可用（实测 0.6s）
        primary=RouteTarget(mcp="akshare-one-mcp", tool="get_realtime_data", source="xueqiu"),
        # 备选：cn-financial 默认源（慢 18s 但通，内部已降级）
        fallback=RouteTarget(mcp="cn-financial-mcp", tool="get_realtime_quote"),
    ),
    "market.get_historical_prices": RoutePolicy(
        capability="market.get_historical_prices",
        # cn-financial 默认源可用（0.8s，内部已降级）
        primary=RouteTarget(mcp="cn-financial-mcp", tool="get_historical_price"),
        # 备选：akshare-one sina 源（0.6s 可用，eastmoney 被风控）
        fallback=RouteTarget(mcp="akshare-one-mcp", tool="get_hist_data", source="sina"),
        # 参数翻译：统一用 period，akshare-one 需要 interval
        param_map={"period": "interval", "daily": "day", "weekly": "week", "monthly": "month"},
    ),
    "market.get_financial_statements": RoutePolicy(
        capability="market.get_financial_statements",
        # 两者走 datacenter 稳定，cn-financial 字段更全
        primary=RouteTarget(mcp="cn-financial-mcp", tool="get_balance_sheet"),
        fallback=RouteTarget(mcp="akshare-one-mcp", tool="get_balance_sheet"),
    ),
    "market.get_valuation": RoutePolicy(
        capability="market.get_valuation",
        primary=RouteTarget(mcp="cn-financial-mcp", tool="get_valuation_metrics"),
    ),
    "market.get_industry_context": RoutePolicy(
        capability="market.get_industry_context",
        primary=RouteTarget(mcp="cn-financial-mcp", tool="get_industry_list"),
    ),
    "market.get_money_flow": RoutePolicy(
        capability="market.get_money_flow",
        primary=RouteTarget(mcp="cn-financial-mcp", tool="get_money_flow"),
        # 注意：此工具实测服务端吞错（{"error":true}），normalizer 须识别
    ),
    "market.get_news": RoutePolicy(
        capability="market.get_news",
        primary=RouteTarget(mcp="cn-financial-mcp", tool="get_stock_news"),
        fallback=RouteTarget(mcp="akshare-one-mcp", tool="get_news_data"),
    ),
}


def get_route(capability: str) -> RoutePolicy | None:
    """查询统一能力的路由策略。未注册的能力返回 None。"""
    return DEFAULT_ROUTES.get(capability)


def translate_arguments(
    capability: str, unified_args: dict[str, Any]
) -> dict[str, Any]:
    """把统一能力的参数翻译为目标 MCP 工具的参数。

    主要处理 akshare-one 的 interval vs period 差异：
    - 统一层用 period=daily/weekly/monthly
    - akshare-one 需要 interval=day/week/month
    其他参数直接透传。
    """
    policy = get_route(capability)
    if policy is None or not policy.param_map:
        return dict(unified_args)

    translated: dict[str, Any] = {}
    for key, value in unified_args.items():
        # 先翻译 key（period→interval）
        mapped_key = policy.param_map.get(key, key)
        # 再翻译 value（daily→day）
        mapped_value = policy.param_map.get(str(value), value)
        translated[mapped_key] = mapped_value
    return translated
