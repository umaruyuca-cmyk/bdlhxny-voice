"""执行器数据链路基线：确定性估值（quantity × price，fail-closed）。"""

from __future__ import annotations

from typing import Any

import pytest

from bdlh_runtime.engine.executor import CatalogToolExecutor


def _executor(**kwargs: Any) -> CatalogToolExecutor:
    return CatalogToolExecutor(None, **kwargs)


@pytest.mark.asyncio
async def test_valuation_computes_market_value_and_weight_deterministically():
    executor = _executor()
    result = await executor(
        "portfolio.build_current_valuation",
        {
            "positions_observation": [
                {"symbol": "300750", "quantity": 100},
                {"symbol": "600519", "quantity": 10},
            ],
            "account_observation": {"cash": 5000.0},
            "quote_observations": [
                {"symbol": "300750", "price": 200.0},
                {"symbol": "600519", "price": 1500.0},
            ],
        },
    )

    assert result["status"] == "SUCCESS"
    assert result["engine"] == "deterministic-valuation"
    assert result["total_market_value"] == 35000.0
    by_symbol = {row["symbol"]: row for row in result["positions"]}
    assert by_symbol["300750"]["market_value"] == 20000.0
    assert by_symbol["300750"]["weight"] == 0.5714
    assert by_symbol["600519"]["weight"] == 0.4286


@pytest.mark.asyncio
async def test_valuation_fail_closed_without_quote_price():
    executor = _executor()
    result = await executor(
        "portfolio.build_current_valuation",
        {
            "positions_observation": [{"symbol": "300750", "quantity": 100}],
            "quote_observations": [{"symbol": "600036", "price": 35.0}],
        },
    )

    assert result["status"] == "FAILED"
    assert "缺少 300750 的价格" in result["error"]


@pytest.mark.asyncio
async def test_valuation_fail_closed_on_invalid_position():
    executor = _executor()
    result = await executor(
        "portfolio.build_current_valuation",
        {"positions_observation": [{"note": "无代码无数量"}], "quote_observations": []},
    )

    assert result["status"] == "FAILED"
    assert "symbol/quantity" in result["error"]
