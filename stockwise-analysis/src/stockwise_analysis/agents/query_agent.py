"""Query Agent 契约与本地开发实现。"""

from __future__ import annotations

import re
from typing import Any, Protocol

from pydantic import BaseModel


class QueryIntent(BaseModel):
    """问题理解节点输出的受控意图，不包含任何工具调用。"""

    analysis_type: str
    symbol: str | None = None
    scope: str | None = None
    requires_portfolio: bool = False
    requires_confirmation: bool = False


class QueryAgent(Protocol):
    """生产 Query Agent 的接口；后续可替换为结构化 LLM 调用。"""

    def understand(self, request: dict[str, Any]) -> QueryIntent:
        """仅理解用户请求，禁止直接查询 MCP、Java 或数据库。"""


class RuleBasedQueryAgent:
    """Phase 0/1 的确定性替身，用于验证 Graph 和契约而非替代模型。"""

    def understand(self, request: dict[str, Any]) -> QueryIntent:
        message = str(request.get("message", ""))
        symbol_match = re.search(r"(?<!\d)([0369]\d{5})(?!\d)", message)
        lowered = message.lower()

        if any(word in message for word in ("综合", "全面", "完整")):
            analysis_type = "comprehensive"
        elif any(word in message for word in ("持仓", "账户", "组合")) or "portfolio" in lowered:
            analysis_type = "portfolio_impact"
        elif any(word in message for word in ("基本面", "财务", "财报")):
            analysis_type = "fundamental"
        elif any(word in message for word in ("估值", "PE", "PB", "市盈率")):
            analysis_type = "valuation"
        elif any(word in message for word in ("技术", "K线", "指标", "趋势")):
            analysis_type = "technical"
        else:
            analysis_type = "market_snapshot"

        return QueryIntent(
            analysis_type=analysis_type,
            symbol=symbol_match.group(1) if symbol_match else request.get("symbol"),
            scope=request.get("scope"),
            requires_portfolio=analysis_type == "portfolio_impact" or "持仓" in message,
            requires_confirmation=bool(request.get("require_confirmation", False)),
        )
