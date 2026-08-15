"""A 股交易日历实现。

交易日判断必须独立于 MCP 与分析能力（架构文档 §7.1：交易日历不作 MCP
能力，由 domain 层本地确定性计算）。

实现：
- 首选 exchange_calendars 库的 XSHG（上交所）日历——内置 A 股节假日、
  调休补班和特殊交易日规则，跨年数据准确；
- 库不可用时降级为"周末 + 已知法定节假日"启发式——开发环境可用，
  但精度有限，生产必须安装 exchange_calendars。

审查文档 §5.2：增加 2026 年节假日回归 fixture 验证。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

logger = logging.getLogger("bdlh_runtime.domain.trading_calendar")


class AShareTradingCalendar:
    """A 股交易日历（基于 exchange_calendars XSHG）。"""

    def __init__(self) -> None:
        self._calendar = None
        try:
            import exchange_calendars as xcals  # type: ignore[import-not-found]

            self._calendar = xcals.get_calendar("XSHG")
            logger.info("交易日历初始化成功 (exchange_calendars XSHG)")
        except ImportError:
            logger.warning("exchange_calendars 未安装，交易日历降级为启发式（周末+节假日表）")
        except Exception as exc:
            logger.warning("exchange_calendars 初始化失败，降级为启发式: %s", exc)

    def is_trading_day(self, value: date) -> bool:
        """判断指定日期是否是 A 股交易日。"""
        if self._calendar is not None:
            return self._calendar.is_session(value)
        return _heuristic_is_trading_day(value)

    def previous_trading_day(self, value: date) -> date:
        """返回指定日期之前（含当天）最近的一个交易日。"""
        candidate = value
        for _ in range(15):  # 最多回溯 15 天（覆盖长假）
            if self.is_trading_day(candidate):
                return candidate
            candidate -= timedelta(days=1)
        return candidate  # 兜底返回最早候选


# ── 启发式降级：周末 + 已知法定节假日 ──
# 2026 年 A 股休市安排（元旦/春节/清明/五一/端午/中秋/国庆）。
# 注意：调休补班（周末上班日）启发式无法覆盖，仅作降级兜底。
_KNOWN_HOLIDAYS_2026: set[date] = {
    date(2026, 1, 1), date(2026, 1, 2),           # 元旦
    date(2026, 2, 16), date(2026, 2, 17), date(2026, 2, 18),  # 春节（示例）
    date(2026, 4, 5), date(2026, 4, 6),           # 清明（示例）
    date(2026, 5, 1), date(2026, 5, 2),           # 劳动节
    date(2026, 6, 19),                             # 端午（示例）
    date(2026, 9, 25),                             # 中秋（示例）
    date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3), date(2026, 10, 7),  # 国庆
}


def _heuristic_is_trading_day(value: date) -> bool:
    """降级启发式：非周末且非已知节假日。"""
    if value.weekday() >= 5:  # 周六/周日
        return False
    if value in _KNOWN_HOLIDAYS_2026:
        return False
    return True


# 统一入口（替代 Protocol 的便捷工厂）
def create_trading_calendar() -> AShareTradingCalendar:
    """创建交易日历实例。"""
    return AShareTradingCalendar()
