"""回测引擎：确定性、无未来函数。

回测是系统可信度的根基（架构文档 v3.1 §1.1"确定性的东西做成硬工具，
agent 管不到内部"）。本引擎严格保证：

1. 无未来函数：第 i 天的持仓由第 i 天的信号决定，成交价用当日收盘价；
   信号序列由策略基于截至当天的数据生成，不泄露未来信息。
2. 可复现：纯函数，相同输入（价格+策略）永远相同输出。
3. 零框架依赖：不 import LangGraph/LangChain/Letta/Mem0。

交易规则（简化但无歧义）：
- 信号 1 → 持有；信号 0 → 空仓（现金，无利息）；
- 换仓在信号变化当天的收盘价成交（同日信号同日执行，无延迟偏差）；
- 不模拟手续费/滑点（可通过 cost_bps 参数近似，默认 0）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import risk as risk_metrics
from .strategy import Strategy


@dataclass
class BacktestResult:
    """回测结果：收益统计 + 逐日权益曲线。"""

    strategy_name: str
    initial_capital: float
    final_equity: float
    total_return: float
    annualized_return: float | None
    sharpe: float | None
    max_drawdown: float | None
    win_rate: float | None          # 盈利交易日占比
    trade_count: int                # 换仓次数
    equity_curve: list[float] = field(default_factory=list)  # 逐日权益
    # 指标参数和版本，供溯源
    params: dict[str, Any] = field(default_factory=dict)
    engine_version: str = "backtest.v1"

    def to_dict(self) -> dict[str, Any]:
        """转为纯 dict，供 AnalysisResult.calculated_indicators 使用。"""
        return {
            "strategy": self.strategy_name,
            "engine": self.engine_version,
            "initial_capital": self.initial_capital,
            "final_equity": round(self.final_equity, 2),
            "total_return": round(self.total_return, 4),
            "annualized_return": round(self.annualized_return, 4) if self.annualized_return is not None else None,
            "sharpe": round(self.sharpe, 4) if self.sharpe is not None else None,
            "max_drawdown": round(self.max_drawdown, 4) if self.max_drawdown is not None else None,
            "win_rate": round(self.win_rate, 4) if self.win_rate is not None else None,
            "trade_count": self.trade_count,
            "params": self.params,
        }


def run_backtest(
    closes: list[float],
    strategy: Strategy,
    *,
    initial_capital: float = 100_000.0,
    cost_bps: float = 0.0,
) -> BacktestResult:
    """运行回测（纯函数，无副作用）。

    输入收盘价序列（时间正序）和策略，输出 BacktestResult。
    校验：价格序列非空且为正；策略信号长度与价格一致。
    """

    if not closes:
        raise ValueError("closes must not be empty")
    if any(c <= 0 for c in closes):
        raise ValueError("prices must be positive")

    signals = strategy.generate_signals(closes)
    if len(signals) != len(closes):
        raise ValueError(f"strategy {strategy.name} produced {len(signals)} signals for {len(closes)} prices")

    # ── 逐日权益模拟 ──
    equity = initial_capital
    equity_curve: list[float] = []
    position = 0.0
    trade_count = 0
    daily_returns: list[float] = []
    prev_equity = initial_capital

    for i in range(len(closes)):
        new_position = float(signals[i])
        if new_position != position:
            # 首日建仓（i==0，position 初始 0）不算换仓；之后信号变化才算
            if i > 0:
                trade_count += 1
            position = new_position
            # 交易成本按换仓金额比例扣除（首日建仓也扣成本）
            equity *= (1.0 - cost_bps / 10000.0)

        # 当日收益 = 持仓比例 × 当日价格变动
        if i > 0:
            price_return = closes[i] / closes[i - 1] - 1.0
            daily_return = position * price_return
            equity *= (1.0 + daily_return)
            daily_returns.append(daily_return)
        else:
            daily_returns.append(0.0)

        equity_curve.append(equity)
        prev_equity = equity

    # ── 统计指标 ──
    total_return = equity / initial_capital - 1.0
    annualized = risk_metrics.annualized_return(equity_curve)
    sharpe = risk_metrics.sharpe_ratio(daily_returns)
    max_dd = risk_metrics.maximum_drawdown(equity_curve)
    win_rate = sum(1 for r in daily_returns if r > 0) / len(daily_returns) if daily_returns else None

    return BacktestResult(
        strategy_name=strategy.name,
        initial_capital=initial_capital,
        final_equity=equity,
        total_return=total_return,
        annualized_return=annualized,
        sharpe=sharpe,
        max_drawdown=max_dd,
        win_rate=win_rate,
        trade_count=trade_count,
        equity_curve=[round(v, 2) for v in equity_curve],
        params={
            "initial_capital": initial_capital,
            "cost_bps": cost_bps,
            "strategy_params": _strategy_params(strategy),
        },
    )


def _strategy_params(strategy: Strategy) -> dict[str, Any]:
    """提取策略参数用于溯源（ma_cross 的窗口等）。"""
    params: dict[str, Any] = {}
    for attr in ("fast_window", "slow_window"):
        if hasattr(strategy, attr):
            params[attr] = getattr(strategy, attr)
    return params


def compare_strategies(
    closes: list[float],
    strategies: list[Strategy],
    *,
    initial_capital: float = 100_000.0,
) -> dict[str, dict[str, Any]]:
    """对比多个策略的回测结果，用于策略选择报告。

    返回 {策略名: to_dict() 结果}。buy_and_hold 作为基准对比。
    """

    return {
        s.name: run_backtest(closes, s, initial_capital=initial_capital).to_dict()
        for s in strategies
    }
