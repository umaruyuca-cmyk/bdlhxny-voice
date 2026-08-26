"""GT-2:冻结集按批次可配——冻结返回的读取口径。

冻结返回读取回归。deep_search 冻结行经 changes/ SQL 补录,镜像同步由
test_frozen_fixture_sync 守卫。
"""

from __future__ import annotations

from bdlh_runtime.evaluation.frozen_observations import FrozenObservations
from tests.eval.frozen_fixtures import frozen_payload


def test_deep_search_frozen_row_is_served() -> None:
    """GT-2 补录验证:deep_search 不再吃 unknown tool 失败桩。"""
    frozen = FrozenObservations(frozen_payload())
    result = frozen.get("research.deep_search")
    assert "conclusion" in result and result["sources"]
    assert frozen.get("market.get_realtime_quote")["price"] == 185.50
