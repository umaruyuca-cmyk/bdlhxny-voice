"""A/B eval canned tool results（MockExecutor 按工具名返回这些桩数据）。

两组共用同一份 canned 数据，隔离工具执行质量差异——唯一变量是
有没有 Agent 工程模式（Guardrail Middleware / Selective Loading /
Fast-Path / Output Guardrail）。
"""

from __future__ import annotations

from typing import Any

CANNED: dict[str, dict[str, Any]] = {
    "market.resolve_instrument": {
        "symbol": "300750",
        "name": "宁德时代",
        "exchange": "SZSE",
        "industry": "电池",
    },
    "market.get_realtime_quote": {
        "symbol": "300750",
        "name": "宁德时代",
        "price": 185.50,
        "change": -2.30,
        "pct_change": -1.22,
        "volume": 1234567,
        "timestamp": "2026-08-19 14:32:00",
    },
    "market.get_valuation": {
        "symbol": "300750",
        "pe_ttm": 28.5,
        "pb": 5.2,
        "pe_percentile": 0.65,
        "pb_percentile": 0.45,
    },
    "market.get_financial_statements": {
        "symbol": "300750",
        "revenue_yoy": 0.153,
        "net_margin": 0.121,
        "roe": 0.187,
        "gross_margin": 0.221,
    },
    "market.get_historical_prices": {
        "symbol": "300750",
        "prices": [
            {"date": "2026-08-18", "open": 187.0, "high": 188.5, "low": 184.2, "close": 185.5, "volume": 1234567},
            {"date": "2026-08-15", "open": 182.0, "high": 186.0, "low": 181.5, "close": 185.0, "volume": 987654},
        ],
    },
    "market.get_industry_context": {
        "industry": "电池",
        "rank": 1,
        "market_share": 0.32,
        "industry_pe_median": 22.3,
    },
    "market.get_news": {
        "items": [
            {"title": "宁德时代发布半年报", "source": "深交所", "time": "2026-08-18"},
            {"title": "固态电池技术突破", "source": "科技日报", "time": "2026-08-15"},
        ],
    },
    "market.get_money_flow": {
        "net_inflow": -1234567.89,
        "main_force": "net_outflow",
        "super_large": -2345678.90,
    },
    "research.web_search": {
        "results": [
            {"title": "固态电池最新进展", "url": "https://example.com/1", "snippet": "宁德时代固态电池取得突破性进展"},
            {"title": "新能源行业分析", "url": "https://example.com/2", "snippet": "2026年新能源电池行业持续增长"},
        ],
    },
    "portfolio.get_current_positions": {
        "positions": [
            {"symbol": "300750", "name": "宁德时代", "quantity": 200, "cost": 150.0, "weight": 0.18},
            {"symbol": "600519", "name": "贵州茅台", "quantity": 50, "cost": 1680.0, "weight": 0.22},
        ],
    },
    "portfolio.get_account_snapshot": {
        "cash": 50000,
        "total_assets": 87100,
        "market_value": 37100,
        "total_cost": 30000,
    },
    "portfolio.get_transaction_history": {
        "transactions": [
            {"date": "2026-07-15", "symbol": "300750", "action": "buy", "quantity": 100, "price": 150.0},
            {"date": "2026-06-20", "symbol": "600519", "action": "buy", "quantity": 50, "price": 1680.0},
        ],
    },
    "portfolio.build_current_valuation": {
        "market_value": 37100,
        "total_cost": 30000,
        "pnl": 7100,
        "pnl_pct": 0.237,
    },
    "user.get_risk_profile": {
        "risk_tolerance": "moderate",
        "risk_level": "R3",
        "description": "稳健型",
    },
    "analysis.run_analysis": {
        "score": 72,
        "rating": "中性偏强",
        "dimensions": {
            "technical": 78,
            "fundamental": 74,
            "valuation": 52,
            "money_flow": 65,
            "sentiment": 71,
        },
        "findings": ["技术面短期超买", "基本面营收增长稳健", "估值高于行业中位数"],
    },
    "memory.recall": {
        "records": ["两年内换房"],
        "degraded": False,
    },
}

_CANNED_600519: dict[str, dict[str, Any]] = {
    "market.get_realtime_quote": {
        "symbol": "600519",
        "name": "贵州茅台",
        "price": 1685.00,
        "change": 12.50,
        "pct_change": 0.75,
        "volume": 234567,
        "timestamp": "2026-08-19 14:32:00",
    },
    "market.get_valuation": {
        "symbol": "600519",
        "pe_ttm": 32.1,
        "pb": 11.2,
        "pe_percentile": 0.72,
        "pb_percentile": 0.85,
    },
    "market.resolve_instrument": {
        "symbol": "600519",
        "name": "贵州茅台",
        "exchange": "SHSE",
        "industry": "白酒",
    },
}


def get_canned(tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return canned result; 600519 覆盖部分行情/估值数据。"""
    symbol = (arguments or {}).get("symbol", "")
    if symbol == "600519" and tool_name in _CANNED_600519:
        return _CANNED_600519[tool_name]
    return CANNED.get(tool_name, {"status": "FAILED", "error": f"unknown tool: {tool_name}"})
