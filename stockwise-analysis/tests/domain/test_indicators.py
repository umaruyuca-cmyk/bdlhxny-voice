"""技术指标计算测试：正确性 + 防未来函数 + 边界。"""

from __future__ import annotations

from stockwise_analysis.domain.indicators import (
    atr_series,
    exponential_moving_average_series,
    macd_series,
    rsi_series,
    simple_moving_average,
    sma_series,
)


# ── SMA ──


def test_sma_basic():
    """SMA 手工验证：1,2,3,4,5 的 3 日均值 = 4。"""
    assert simple_moving_average([1, 2, 3, 4, 5], 3) == 4.0


def test_sma_insufficient_samples():
    """样本不足返回 None。"""
    assert simple_moving_average([1, 2], 3) is None


def test_sma_series_prefix_none():
    """滚动 SMA 前 window-1 个位置是 None。"""
    result = sma_series([1, 2, 3, 4], 3)
    assert result[:2] == [None, None]
    assert result[2] == 2.0
    assert result[3] == 3.0


# ── EMA ──


def test_ema_known_sequence():
    """EMA 已知值验证：alpha=1（span→∞ 极端）时 EMA 等于当前值。"""
    # span=1 时 alpha=1，EMA 就是原值
    result = exponential_moving_average_series([1.0, 2.0, 3.0], 1)
    assert result == [1.0, 2.0, 3.0]


def test_ema_seed_is_first_value():
    """EMA 种子是第一个值。"""
    result = exponential_moving_average_series([10.0, 12.0], 3)
    assert result[0] == 10.0
    # 第二个值 = 0.5*12 + 0.5*10 = 11
    assert abs(result[1] - 11.0) < 1e-9


# ── MACD ──


def test_macd_structure():
    """MACD 返回三线，长度与输入一致。"""
    closes = [float(i) for i in range(1, 41)]  # 40 个值 (1..40)
    result = macd_series(closes)
    assert set(result.keys()) == {"dif", "dea", "histogram"}
    assert len(result["dif"]) == 40
    # 前 slow_span-1=25 个位置 DIF 为 None（EMA26 未收敛）
    assert result["dif"][24] is None
    assert result["dif"][25] is not None


def test_macd_empty():
    """空输入返回空三线。"""
    result = macd_series([])
    assert result == {"dif": [], "dea": [], "histogram": []}


# ── RSI ──


def test_rsi_all_up_is_100():
    """连续上涨的 RSI 应为 100。"""
    prices = [float(i) for i in range(1, 30)]  # 单调递增
    result = rsi_series(prices, 14)
    assert result[-1] == 100.0


def test_rsi_all_down_is_0():
    """连续下跌的 RSI 应为 0。"""
    prices = [float(30 - i) for i in range(30)]  # 单调递减
    result = rsi_series(prices, 14)
    assert result[-1] == 0.0


def test_rsi_insufficient_samples():
    """样本不足（< window+1）时全 None。"""
    result = rsi_series([1.0, 2.0], 14)
    assert result == [None, None]


# ── ATR ──


def test_atr_constant_range():
    """恒定振幅时 ATR 应等于振幅。"""
    highs = [101.0] * 20
    lows = [99.0] * 20
    closes = [100.0] * 20
    result = atr_series(highs, lows, closes, 14)
    assert result[-1] == 2.0  # TR 恒为 high-low = 2


def test_atr_length_mismatch_raises():
    """OHLC 长度不一致抛 ValueError。"""
    try:
        atr_series([1.0, 2.0], [1.0], [1.0, 2.0])
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


# ── 防未来函数 ──


def test_sma_series_no_future_leak():
    """SMA 序列第 i 个值只依赖前 i+1 个输入（防未来函数验证）。"""
    # 构造序列：前面都是 1，最后一个跳变到 100
    values = [1.0] * 10 + [100.0]
    result = sma_series(values, 5)
    # 第 9 个位置（跳变前）的 5 日均值 = 1
    assert result[9] == 1.0
    # 第 10 个位置（含跳变）才反映 100
    assert result[10] == (1.0 * 4 + 100.0) / 5
