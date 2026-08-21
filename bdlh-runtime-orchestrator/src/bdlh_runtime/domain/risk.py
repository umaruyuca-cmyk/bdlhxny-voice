"""确定性风险指标。

所有函数都是纯函数，输入价格序列（时间正序）输出确定性指标。
风险指标用于：
- 波动率：衡量价格不确定性，供仓位计算和风险标记使用；
- 最大回撤：衡量最坏持有期亏损；
- 支撑/阻力位：技术分析的区间判断（基于已发生数据，无未来函数）。
"""

from __future__ import annotations

from collections.abc import Sequence
from math import sqrt

# 交易日常数：A 股每年约 244 个交易日，用于年化
_TRADING_DAYS_PER_YEAR = 244.0


def maximum_drawdown(values: Sequence[float]) -> float | None:
    """计算价格序列最大回撤，返回范围为 ``[-1, 0]``。

    最大回撤 = min(当前价/历史峰值 - 1)。只使用截至当前的价格，
    无未来函数。
    """

    if not values:
        return None
    peak = values[0]
    drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            drawdown = min(drawdown, value / peak - 1.0)
    return drawdown


def annualized_volatility(returns: Sequence[float]) -> float | None:
    """年化波动率：日收益率标准差 × sqrt(244)。

    输入为收益率序列（如 simple_returns 的输出）。样本不足 2 个返回 None。
    """

    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return sqrt(max(variance, 0.0)) * sqrt(_TRADING_DAYS_PER_YEAR)


def annualized_return(prices: Sequence[float]) -> float | None:
    """年化收益率（几何年化，基于首尾价格和交易日跨度）。

    返回比率（0.1 表示 10%）。价格不足 2 个返回 None。
    """

    if len(prices) < 2:
        return None
    first, last = prices[0], prices[-1]
    if first <= 0:
        return None
    total_return = last / first
    years = (len(prices) - 1) / _TRADING_DAYS_PER_YEAR
    if years <= 0:
        return None
    return total_return ** (1.0 / years) - 1.0


def support_resistance(
    highs: Sequence[float],
    lows: Sequence[float],
    lookback: int = 20,
) -> dict[str, float | None]:
    """支撑位与阻力位（过去 N 日高低点的分位）。

    支撑位 = 过去 lookback 日最低价的 25 分位；阻力位 = 最高价的 75 分位。
    只用已发生数据，无未来函数。
    """

    if not highs or not lows or len(highs) != len(lows):
        return {"support": None, "resistance": None}
    if lookback <= 0:
        raise ValueError("lookback must be positive")

    window_highs = list(highs[-lookback:])
    window_lows = list(lows[-lookback:])
    if not window_highs or not window_lows:
        return {"support": None, "resistance": None}

    support = min(window_lows) + (max(window_lows) - min(window_lows)) * 0.25
    resistance = min(window_highs) + (max(window_highs) - min(window_highs)) * 0.75
    return {"support": support, "resistance": resistance}


def sharpe_ratio(returns: Sequence[float], risk_free_rate: float = 0.0) -> float | None:
    """夏普比率：(日收益均值 - 无风险日收益) / 日收益标准差 × sqrt(244)。

    risk_free_rate 为年化无风险利率（如 0.02 表示 2%），内部转日化。
    用于组合/标的的风险调整收益对比。
    """

    if len(returns) < 2:
        return None
    daily_rf = risk_free_rate / _TRADING_DAYS_PER_YEAR
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = sqrt(max(variance, 0.0))
    if std == 0:
        return None
    return (mean - daily_rf) / std * sqrt(_TRADING_DAYS_PER_YEAR)
