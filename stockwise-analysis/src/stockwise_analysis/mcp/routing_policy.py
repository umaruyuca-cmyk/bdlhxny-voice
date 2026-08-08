"""市场统一能力的主备路由策略。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoutePolicy:
    """一个统一能力的主源和最多一次同源备用调用规则。"""

    capability: str
    primary: str
    fallback: str | None = None


DEFAULT_ROUTES = {
    "market.resolve_instrument": RoutePolicy("market.resolve_instrument", "cn-financial-mcp"),
    "market.get_realtime_quote": RoutePolicy("market.get_realtime_quote", "cn-financial-mcp", "akshare-one-mcp"),
    "market.get_historical_prices": RoutePolicy("market.get_historical_prices", "cn-financial-mcp", "akshare-one-mcp"),
    "market.get_financial_statements": RoutePolicy("market.get_financial_statements", "cn-financial-mcp", "akshare-one-mcp"),
}
