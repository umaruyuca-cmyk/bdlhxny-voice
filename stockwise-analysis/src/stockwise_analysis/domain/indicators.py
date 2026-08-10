"""确定性技术指标计算。

指标计算属于 Python Domain 层，不接受 MCP 预计算指标作为最终结论——避免
不同数据源参数不一致及未来函数风险（架构文档 v3.1 §8.3 计算责任）。

防未来函数原则：所有指标都是"滚动窗口"计算——第 i 个输出只依赖
values[0..i]，绝不使用未来数据点。这保证回测时指标与信号可复现。

所有函数都是纯函数：无状态、无 I/O、输入输出确定。传入的序列按时间正序
（旧→新），最后一个元素是最近值。
"""

from __future__ import annotations

from collections.abc import Sequence


def simple_moving_average(values: Sequence[float], window: int) -> float | None:
    """计算末尾窗口的简单移动平均；样本不足时返回 ``None``。

    只取序列最后 window 个值，即"截至当前时刻"的 MA。
    """

    if window <= 0:
        raise ValueError("window must be positive")
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def sma_series(values: Sequence[float], window: int) -> list[float | None]:
    """滚动 SMA 序列：第 i 个输出是 values[0..i] 的 window 均值。

    前 window-1 个位置返回 None（样本不足）。这是防未来函数的标准形态——
    每个时刻只用过去 window 个数据点。
    """

    if window <= 0:
        raise ValueError("window must be positive")
    result: list[float | None] = []
    for i in range(len(values)):
        if i + 1 < window:
            result.append(None)
        else:
            result.append(sum(values[i - window + 1 : i + 1]) / window)
    return result


def exponential_moving_average_series(
    values: Sequence[float], span: int
) -> list[float]:
    """滚动 EMA 序列（平滑系数 2/(span+1)）。

    EMA[0] = values[0]（种子），之后 EMA[i] = α*values[i] + (1-α)*EMA[i-1]。
    与主流技术分析库（pandas ewm）同一定义，保证跨实现可复现。
    """

    if span <= 0:
        raise ValueError("span must be positive")
    alpha = 2.0 / (span + 1.0)
    result: list[float] = []
    ema: float | None = None
    for value in values:
        ema = value if ema is None else alpha * value + (1.0 - alpha) * ema
        result.append(ema)
    return result


def macd_series(
    values: Sequence[float],
    fast_span: int = 12,
    slow_span: int = 26,
    signal_span: int = 9,
) -> dict[str, list[float | None]]:
    """MACD 三线序列：DIF、DEA(signal)、MACD柱。

    标准参数 12/26/9。DIF = EMA12 - EMA26；DEA = DIF 的 EMA9；
    MACD柱 = 2 * (DIF - DEA)。前 slow_span-1 个位置 DIF 为 None
    （EMA26 尚未收敛，样本不足）。

    返回 dict，避免 tuple 顺序混淆。
    """

    if not values:
        return {"dif": [], "dea": [], "histogram": []}

    ema_fast = exponential_moving_average_series(values, fast_span)
    ema_slow = exponential_moving_average_series(values, slow_span)

    # DIF：前 slow_span-1 个位置样本不足（EMA26 冷启动不可靠）
    dif: list[float | None] = []
    for i in range(len(values)):
        dif.append(ema_fast[i] - ema_slow[i] if i >= slow_span - 1 else None)

    # DEA：对 DIF 非空段做 EMA9，前面保持 None
    valid_dif = [v for v in dif if v is not None]
    dea_valid = exponential_moving_average_series(valid_dif, signal_span) if valid_dif else []
    dea: list[float | None] = []
    j = 0
    for v in dif:
        if v is None:
            dea.append(None)
        else:
            dea.append(dea_valid[j])
            j += 1

    histogram: list[float | None] = []
    for i in range(len(values)):
        if dif[i] is not None and dea[i] is not None:
            histogram.append(2.0 * (dif[i] - dea[i]))  # 国内习惯乘 2
        else:
            histogram.append(None)

    return {"dif": dif, "dea": dea, "histogram": histogram}


def rsi_series(values: Sequence[float], window: int = 14) -> list[float | None]:
    """RSI 序列（Wilder 平滑法）。

    RSI = 100 - 100/(1 + RS)，RS = 平均涨幅/平均跌幅。使用 Wilder 的
    递归平滑（与 TA-Lib 一致），前 window 个位置返回 None（样本不足）。
    """

    if window <= 0:
        raise ValueError("window must be positive")
    if len(values) < window + 1:
        return [None] * len(values)

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    result: list[float | None] = [None] * len(values)

    # 首个窗口的简单平均
    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window
    result[window] = _rsi_value(avg_gain, avg_loss)

    # Wilder 递归平滑
    for i in range(window, len(gains)):
        avg_gain = (avg_gain * (window - 1) + gains[i]) / window
        avg_loss = (avg_loss * (window - 1) + losses[i]) / window
        result[i + 1] = _rsi_value(avg_gain, avg_loss)

    return result


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    """由平均涨跌幅计算 RSI 值（0-100 区间）。"""
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def atr_series(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    window: int = 14,
) -> list[float | None]:
    """ATR 序列（Wilder 平滑法）。

    真实波幅 TR = max(high-low, |high-prev_close|, |low-prev_close|)，
    ATR 为 TR 的 Wilder 均值。用于波动率和止损位计算。
    """

    if window <= 0:
        raise ValueError("window must be positive")
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs/lows/closes must have same length")

    trs: list[float] = []
    for i in range(len(closes)):
        if i == 0:
            trs.append(highs[i] - lows[i])
        else:
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)

    result: list[float | None] = [None] * len(closes)
    if len(trs) < window:
        return result

    atr = sum(trs[:window]) / window
    result[window - 1] = atr
    for i in range(window, len(trs)):
        atr = (atr * (window - 1) + trs[i]) / window
        result[i] = atr
    return result
