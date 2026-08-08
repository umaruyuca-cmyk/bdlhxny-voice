"""确定性技术指标计算。

指标计算属于 Python Domain 层，不接受 MCP 预计算指标作为最终结论，避免不同
数据源参数不一致及未来函数风险。
"""

from __future__ import annotations

from collections.abc import Sequence


def simple_moving_average(values: Sequence[float], window: int) -> float | None:
    """计算末尾窗口的简单移动平均；样本不足时返回 ``None``。"""

    if window <= 0:
        raise ValueError("window must be positive")
    if len(values) < window:
        return None
    return sum(values[-window:]) / window
