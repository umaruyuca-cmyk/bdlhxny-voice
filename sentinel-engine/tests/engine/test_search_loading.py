"""search 装载模式：命中 / 未命中回退 / 缓存 / 预算扣减（WO-T2-4）。"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from bdlh_runtime.engine.loader import ToolLoader
from bdlh_runtime.engine.loop import AgentLoop, AgentTurn
from bdlh_runtime.tools.catalog import catalog_from_snapshot
from bdlh_runtime.tools.search import SEARCH_TOOLS_NAME
from tests.engine.test_loop import FakeChatModel, _echo
from tests.helpers_encoder import LexicalEncoder

HIT_QUERY = "实时报价 最新价"
MISS_QUERY = "qqqqxxxxzzzz"
HISTORY_QUERY = "历史行情 K线 OHLCV"


def _search_call(query: str, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": SEARCH_TOOLS_NAME,
                "args": {"query": query},
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


def _bound_names(llm: FakeChatModel, round_index: int) -> set[str]:
    names: set[str] = set()
    for spec in llm.bind_history[round_index]:
        names.add(spec["function"]["name"])
    return names


def _loop(registry_snapshot, llm: FakeChatModel, *, max_tool_calls: int = 20) -> AgentLoop:
    return AgentLoop(
        llm=llm,
        catalog=catalog_from_snapshot(registry_snapshot),
        executor=_echo,
        tool_loading="search",
        encoder=LexicalEncoder(),
        max_tool_calls=max_tool_calls,
    )


class TestSearchHit:
    @pytest.mark.asyncio
    async def test_hit_loads_quote_into_next_bind(self, registry_snapshot):
        llm = FakeChatModel(
            [
                _search_call(HIT_QUERY, "s1"),
                AIMessage(content="已找到实时报价工具。"),
            ]
        )
        result = await _loop(registry_snapshot, llm).run(
            AgentTurn(user_id="u1", message="宁德时代现在什么价", scene_tag="market")
        )
        assert result.entered_loop is True
        assert _bound_names(llm, 0) == {SEARCH_TOOLS_NAME}
        assert "market.get_realtime_quote" in _bound_names(llm, 1)
        assert SEARCH_TOOLS_NAME in _bound_names(llm, 1)
        assert result.audits[0].tool_name == SEARCH_TOOLS_NAME
        assert result.audits[0].status == "SUCCESS"
        payload = json.loads([m for m in result.messages if isinstance(m, ToolMessage)][0].content)
        assert "market.get_realtime_quote" in payload["data"]["names"]


class TestSearchMissFallback:
    @pytest.mark.asyncio
    async def test_two_consecutive_misses_fall_back_to_scoped_wide_pack(self, registry_snapshot):
        llm = FakeChatModel(
            [
                _search_call(MISS_QUERY, "m1"),
                _search_call(f"{MISS_QUERY} zz", "m2"),
                AIMessage(content="改用宽包继续。"),
            ]
        )
        loop = _loop(registry_snapshot, llm)
        result = await loop.run(AgentTurn(user_id="u1", message="随便问问", scene_tag="market"))
        assert result.audits[0].status == "SUCCESS"
        assert result.audits[1].status == "SUCCESS"
        assert _bound_names(llm, 0) == {SEARCH_TOOLS_NAME}
        assert _bound_names(llm, 1) == {SEARCH_TOOLS_NAME}
        wide = _bound_names(llm, 2)
        assert SEARCH_TOOLS_NAME not in wide
        assert "market.get_realtime_quote" in wide
        assert loop._loader.fallback_active is True

    def test_single_miss_does_not_fallback(self, registry_snapshot):
        loader = ToolLoader(
            catalog_from_snapshot(registry_snapshot),
            tool_loading="search",
            encoder=LexicalEncoder(),
        )
        first = loader.run_search(MISS_QUERY, top_k=3, scene_tag="market", authenticated=False)
        assert first["count"] == 0
        assert first["fallback"] is False
        names = {card.name for card in loader.load_for_turn("market", authenticated=False)}
        assert names == {SEARCH_TOOLS_NAME}


class TestSearchCache:
    def test_hits_stay_loaded_across_searches(self, registry_snapshot):
        loader = ToolLoader(
            catalog_from_snapshot(registry_snapshot),
            tool_loading="search",
            encoder=LexicalEncoder(),
        )
        first = loader.run_search(HIT_QUERY, top_k=3, scene_tag="research", authenticated=False)
        assert "market.get_realtime_quote" in first["names"]
        second = loader.run_search(HISTORY_QUERY, top_k=3, scene_tag="research", authenticated=False)
        packed = {card.name for card in loader.load_for_turn("research", authenticated=False)}
        assert "market.get_realtime_quote" in packed
        assert "market.get_historical_prices" in second["names"]
        assert "market.get_realtime_quote" in loader.cached_names

    @pytest.mark.asyncio
    async def test_session_cache_avoids_dropping_prior_hit(self, registry_snapshot):
        llm = FakeChatModel(
            [
                _search_call(HIT_QUERY, "c1"),
                _search_call(HISTORY_QUERY, "c2"),
                AIMessage(content="缓存仍在。"),
            ]
        )
        result = await _loop(registry_snapshot, llm).run(
            AgentTurn(user_id="u1", message="先报价再看走势", scene_tag="research")
        )
        assert "market.get_realtime_quote" in _bound_names(llm, 1)
        assert "market.get_realtime_quote" in _bound_names(llm, 2)
        assert result.audits[0].status == "SUCCESS"
        assert result.audits[1].status == "SUCCESS"


class TestSearchBudget:
    @pytest.mark.asyncio
    async def test_search_tools_counts_toward_budget(self, registry_snapshot):
        llm = FakeChatModel(
            [
                _search_call(HIT_QUERY, "b1"),
                _search_call(HIT_QUERY, "b2"),
                AIMessage(content="预算已尽。"),
            ]
        )
        result = await _loop(registry_snapshot, llm, max_tool_calls=1).run(
            AgentTurn(user_id="u1", message="报价", scene_tag="market")
        )
        assert result.audits[0].tool_name == SEARCH_TOOLS_NAME
        assert result.audits[0].status == "SUCCESS"
        assert result.audits[1].tool_name == SEARCH_TOOLS_NAME
        assert result.audits[1].status == "REJECTED"
        assert result.audits[1].audit_code == "TOOL_BUDGET_EXCEEDED"
        payload = json.loads([m for m in result.messages if isinstance(m, ToolMessage)][1].content)
        assert payload["rejected"] is True
        assert payload["audit_code"] == "TOOL_BUDGET_EXCEEDED"
