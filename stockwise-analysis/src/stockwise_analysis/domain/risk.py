"""确定性风险指标。"""

from __future__ import annotations

from collections.abc import Sequence


def maximum_drawdown(values: Sequence[float]) -> float | None:
    """计算价格序列最大回撤，返回范围为 ``[-1, 0]``。"""

    if not values:
        return None
    peak = values[0]
    drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            drawdown = min(drawdown, value / peak - 1.0)
    return drawdown
