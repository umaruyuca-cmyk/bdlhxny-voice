"""本地开发 Mock Tool。

这些工具只用于验证 Graph 调度、状态和契约；生产环境必须由 MCP Gateway 与
Java Data Adapter 替换，不能把 Mock 数据伪装成市场事实。
"""

from __future__ import annotations

from .registry import ToolRegistry


def build_mock_registry() -> ToolRegistry:
    """创建最小只读 Mock 工具集合。"""
    registry = ToolRegistry()
    registry.register(
        "market.resolve_instrument",
        "Resolve a market instrument",
        lambda args: {"symbol": args.get("symbol"), "name": f"标的 {args.get('symbol')}"},
    )
    registry.register(
        "market.get_realtime_quote",
        "Return a deterministic mock quote",
        lambda args: {"symbol": args.get("symbol"), "price": None, "is_mock": True},
    )
    registry.register("market.get_historical_prices", "Return deterministic mock historical prices", lambda args: [])
    registry.register(
        "portfolio.get_current_positions",
        "Return a mock user portfolio",
        lambda args: {"positions": [], "is_mock": True},
    )
    return registry
