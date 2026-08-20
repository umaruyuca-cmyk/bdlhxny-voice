"""记忆层测试：NoOp 降级行为 + routing_policy 参数翻译。"""

from __future__ import annotations

import pytest

from bdlh_runtime.integrations.mcp.routing_policy import (
    get_route,
    translate_arguments,
)
from bdlh_runtime.memory import NoOpMemoryStore

# ── NoOpMemoryStore 降级行为 ──


@pytest.mark.asyncio
async def test_noop_search_returns_empty():
    """NoOp 的 search 必须返回空列表，不抛异常。"""
    store = NoOpMemoryStore()
    result = await store.search("任何查询", "user-1")
    assert result == []


@pytest.mark.asyncio
async def test_noop_add_does_not_raise():
    """NoOp 的 add 必须静默成功，不抛异常、不阻塞。"""
    store = NoOpMemoryStore()
    await store.add("一些内容", "user-1")  # 不应抛异常


# ── routing_policy 参数翻译 ──


def test_period_translated_to_interval_for_historical_prices():
    """历史K线的 period=daily 应翻译为 akshare-one 的 interval=day。"""
    translated = translate_arguments(
        "market.get_historical_prices",
        {"symbol": "600519", "period": "daily", "lookback_days": 120},
    )
    assert translated["interval"] == "day"
    assert "period" not in translated
    assert translated["symbol"] == "600519"


def test_lookback_days_translated_to_date_range():
    """lookback_days 应翻译为 start_date/end_date 日期区间（cn-financial 契约）。"""
    translated = translate_arguments(
        "market.get_historical_prices",
        {"symbol": "600519", "period": "daily", "lookback_days": 120},
    )
    assert "lookback_days" not in translated
    assert "start_date" in translated and "end_date" in translated
    # 日期格式 YYYY-MM-DD 且区间合理（end >= start）
    assert translated["end_date"] >= translated["start_date"]
    assert translated["start_date"].count("-") == 2


def test_no_translation_for_capabilities_without_param_map():
    """没有 param_map 的能力（如实时行情）参数原样透传。"""
    translated = translate_arguments(
        "market.get_realtime_quote",
        {"symbol": "600519"},
    )
    assert translated == {"symbol": "600519"}


def test_unregistered_capability_returns_original_args():
    """未注册的能力参数原样返回。"""
    translated = translate_arguments("market.unknown", {"x": 1})
    assert translated == {"x": 1}


def test_route_lookup():
    """路由查询能找到已注册能力。"""
    route = get_route("market.get_realtime_quote")
    assert route is not None
    assert route.primary.mcp == "akshare-one-mcp"
    assert route.primary.source == "xueqiu"
    assert route.fallback is not None
    assert route.fallback.mcp == "cn-financial-mcp"


def test_route_lookup_unregistered():
    """未注册能力返回 None。"""
    assert get_route("market.nonexistent") is None
