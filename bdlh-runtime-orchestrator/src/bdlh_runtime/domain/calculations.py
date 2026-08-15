"""与具体模型无关的领域计算。"""

from __future__ import annotations

from collections.abc import Sequence


def simple_returns(prices: Sequence[float]) -> list[float]:
    """根据相邻价格计算简单收益率；零价格不产生收益率。"""

    returns: list[float] = []
    for previous, current in zip(prices, prices[1:]):
        if previous != 0:
            returns.append(current / previous - 1.0)
    return returns
