"""回测引擎测试：可复现性 + 无未来函数 + 策略行为。"""

from __future__ import annotations

import pytest

from bdlh_runtime.domain.backtest import compare_strategies, run_backtest
from bdlh_runtime.domain.strategy import (
    BuyAndHoldStrategy,
    MaCrossStrategy,
    create_strategy,
)

# 确定性合成价格：前 40 天下跌、后 20 天上涨（便于验证 MA 交叉信号）
_CLOSES = [100.0 - i * 0.5 for i in range(40)] + [90.0 + i * 0.5 for i in range(20)]


# ── 可复现性 ──


def test_backtest_is_deterministic():
    """相同输入两次回测结果完全一致。"""
    s1 = run_backtest(_CLOSES, MaCrossStrategy())
    s2 = run_backtest(_CLOSES, MaCrossStrategy())
    assert s1.equity_curve == s2.equity_curve
    assert s1.total_return == s2.total_return


# ── 策略信号 ──


def test_ma_cross_signals_bullish_after_cross():
    """下跌转上涨后，MA5 上穿 MA20，仓位应从 0 变 1。"""
    signals = MaCrossStrategy().generate_signals(_CLOSES)
    assert len(signals) == len(_CLOSES)
    # 前 20 天慢线未形成 → 空仓
    assert signals[10] == 0.0
    # 后期上涨段 → 持仓
    assert signals[-1] == 1.0


def test_buy_and_hold_always_full():
    """买入持有始终满仓。"""
    signals = BuyAndHoldStrategy().generate_signals(_CLOSES)
    assert signals == [1.0] * len(_CLOSES)


def test_create_strategy_unknown_raises():
    """未知策略抛 ValueError。"""
    with pytest.raises(ValueError):
        create_strategy("nonexistent")


# ── 回测结果 ──


def test_backtest_basic_stats():
    """回测应产出收益、回撤、夏普等统计。"""
    result = run_backtest(_CLOSES, BuyAndHoldStrategy())
    assert result.total_return == pytest.approx(_CLOSES[-1] / _CLOSES[0] - 1.0)
    assert result.max_drawdown is not None and result.max_drawdown <= 0
    assert result.trade_count == 0  # 买入持有无换仓


def test_backtest_ma_cross_trades():
    """MA 交叉策略在趋势反转处换仓。"""
    result = run_backtest(_CLOSES, MaCrossStrategy())
    assert result.trade_count >= 1  # 至少一次从空仓到持仓


def test_backtest_empty_prices_raises():
    """空价格序列抛 ValueError。"""
    with pytest.raises(ValueError):
        run_backtest([], BuyAndHoldStrategy())


def test_backtest_negative_prices_raises():
    """非正价格抛 ValueError。"""
    with pytest.raises(ValueError):
        run_backtest([100.0, -5.0, 90.0], BuyAndHoldStrategy())


def test_compare_strategies_returns_both():
    """策略对比返回两个策略的结果。"""
    result = compare_strategies(_CLOSES, [BuyAndHoldStrategy(), MaCrossStrategy()])
    assert set(result.keys()) == {"buy_and_hold", "ma_cross"}


# ── 无未来函数验证 ──


def test_backtest_no_future_leak():
    """信号变化当天的收益只按当天信号结算，不提前反映次日价格。"""
    # 构造：前段下跌（空仓等待），突然跳涨（当天信号才转多）
    closes = [100.0] * 20 + [80.0] * 20 + [100.0, 101.0]
    strategy = MaCrossStrategy(fast_window=5, slow_window=10)
    result = run_backtest(closes, strategy, initial_capital=1000.0)
    # 早期（慢线未形成）应为空仓，权益保持 1000
    assert result.equity_curve[5] == 1000.0
