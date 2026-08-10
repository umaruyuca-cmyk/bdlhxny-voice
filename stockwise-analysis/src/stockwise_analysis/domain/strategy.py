"""策略设计：确定性信号生成。

策略是"信号生成器"——输入价格序列，输出多空仓位信号序列，供回测引擎消费。
核心保证（与指标一致）：
- 防未来函数：第 i 天的信号只依赖截至第 i 天的数据；
- 纯函数：相同输入永远相同输出；
- 确定性：不依赖 LLM、随机数或外部状态。

信号约定：position 取值 1（满仓多头）/ 0（空仓）/ -1（做空，暂不启用）。
默认只用 1/0，与 A 股"只能做多"的现实一致。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from . import indicators as ind


class Strategy(Protocol):
    """策略接口：由价格序列生成仓位信号序列。"""

    name: str

    def generate_signals(self, closes: Sequence[float]) -> list[float]:
        """返回与 closes 等长的仓位信号序列（1=持仓，0=空仓）。"""
        ...


class MaCrossStrategy:
    """均线交叉策略：快线上穿慢线买入，下穿卖出。

    经典的双均线趋势跟随策略。信号规则（防未来函数）：
    - 第 i 天：MA_fast(i) 与 MA_slow(i) 比较；
    - 快线从慢线下方穿越到上方 → 仓位 1；
    - 快线从慢线上方跌穿 → 仓位 0；
    - 慢线尚未形成（样本不足）→ 保持 0（空仓等待）。
    """

    name = "ma_cross"

    def __init__(self, fast_window: int = 5, slow_window: int = 20):
        if fast_window >= slow_window:
            raise ValueError("fast_window must be smaller than slow_window")
        self.fast_window = fast_window
        self.slow_window = slow_window

    def generate_signals(self, closes: Sequence[float]) -> list[float]:
        fast_ma = ind.sma_series(closes, self.fast_window)
        slow_ma = ind.sma_series(closes, self.slow_window)

        signals: list[float] = []
        position = 0.0
        for i in range(len(closes)):
            f, s = fast_ma[i], slow_ma[i]
            if f is None or s is None:
                # 慢线尚未形成，无法判断趋势 → 空仓
                signals.append(0.0)
                continue
            if f > s:
                position = 1.0
            elif f < s:
                position = 0.0
            # f == s 时保持原仓位（避免频繁切换）
            signals.append(position)
        return signals


class BuyAndHoldStrategy:
    """买入持有基准策略：全程满仓。

    作为回测对比的基准（benchmark），用于衡量策略相对买入持有的超额收益。
    """

    name = "buy_and_hold"

    def generate_signals(self, closes: Sequence[float]) -> list[float]:
        if not closes:
            return []
        return [1.0] * len(closes)


def create_strategy(name: str, **kwargs) -> Strategy:
    """按名称创建策略实例。未知策略抛 ValueError。"""
    if name == "ma_cross":
        return MaCrossStrategy(**kwargs)
    if name == "buy_and_hold":
        return BuyAndHoldStrategy()
    raise ValueError(f"未知策略: {name}")
