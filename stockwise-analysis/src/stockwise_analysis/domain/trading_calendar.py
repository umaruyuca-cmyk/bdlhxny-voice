"""中国市场交易日历边界。"""

from __future__ import annotations

from datetime import date
from typing import Protocol


class TradingCalendarProvider(Protocol):
    """交易日判断必须独立于 MCP 与分析能力。"""

    def is_trading_day(self, value: date) -> bool:
        """判断指定日期是否是经验证的交易日。"""
