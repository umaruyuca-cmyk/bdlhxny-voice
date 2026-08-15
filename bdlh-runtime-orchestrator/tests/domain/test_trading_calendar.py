"""交易日历测试（审查文档 §5.2 / §8.5）。

验证：A 股交易日判断正确——节假日休市、工作日开市。
（启发式降级和 exchange_calendars 都覆盖。）
"""

from __future__ import annotations

from datetime import date

from bdlh_runtime.domain.trading_calendar import AShareTradingCalendar


def test_weekend_is_not_trading_day():
    """周末不是交易日。"""
    cal = AShareTradingCalendar()
    # 2026-08-08 是周六
    assert cal.is_trading_day(date(2026, 8, 8)) is False
    # 2026-08-09 是周日
    assert cal.is_trading_day(date(2026, 8, 9)) is False


def test_weekday_is_trading_day():
    """普通工作日是交易日。"""
    cal = AShareTradingCalendar()
    # 2026-08-05 是周三
    assert cal.is_trading_day(date(2026, 8, 5)) is True


def test_known_holiday_not_trading_day():
    """2026 元旦（1月1日）休市。"""
    cal = AShareTradingCalendar()
    assert cal.is_trading_day(date(2026, 1, 1)) is False


def test_previous_trading_day_skips_weekend():
    """前一交易日跳过周末。"""
    cal = AShareTradingCalendar()
    # 2026-08-08 是周六 → 前一交易日是周五 08-07
    assert cal.previous_trading_day(date(2026, 8, 8)) == date(2026, 8, 7)


def test_previous_trading_day_returns_self_if_trading_day():
    """当天是交易日则返回当天。"""
    cal = AShareTradingCalendar()
    assert cal.previous_trading_day(date(2026, 8, 5)) == date(2026, 8, 5)


def test_heuristic_holiday_table_2026():
    """启发式（无 exchange_calendars 时）的 2026 节假日表。"""
    from bdlh_runtime.domain.trading_calendar import _heuristic_is_trading_day

    # 元旦（周四）休市
    assert _heuristic_is_trading_day(date(2026, 1, 1)) is False
    # 劳动节（周五）休市
    assert _heuristic_is_trading_day(date(2026, 5, 1)) is False
    # 国庆（周四）休市
    assert _heuristic_is_trading_day(date(2026, 10, 1)) is False
    # 普通工作日开市
    assert _heuristic_is_trading_day(date(2026, 8, 5)) is True
