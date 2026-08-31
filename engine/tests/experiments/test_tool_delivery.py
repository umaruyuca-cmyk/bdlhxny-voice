"""全量工具、工具搜索与工具缺失实验测试(混合路线 C5)。

全部使用 Fake 编码器 / FakeChatModel / 冻结 Mock 执行器,不调用真实 LLM、
不引入向量数据库(内存等价实现)。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from bdlh_runtime.engine.loader import ToolLoader
from bdlh_runtime.experiments.template_runner import build_template_catalog, run_native_agent
from bdlh_runtime.experiments.templates import CLASSIFICATION_FORMAL, TEMPLATES, plan_template_batch
from bdlh_runtime.experiments.tool_availability import (
    WEATHER_AVAILABILITY_SPEC,
    acceptable_paths_for,
    attribute_search_run,
    judge_tool_availability,
)
from bdlh_runtime.tools.catalog import ToolCard, ToolCatalog
from bdlh_runtime.tools.search import SEARCH_TOOLS_NAME

_VISIBLE = (
    "weather.get_forecast",
    "web.search",
    "calculator.evaluate",
    "document.summarize",
)

_WEATHER_FIXTURE = {
    "tool": "weather.get_forecast",
    "match_mode": "subset",
    "match_arguments": {"location": "上海"},
    "status": "success",
    "result": {"forecast": "多云 25℃", "location": "上海"},
    "fixture_id": "fx-w1",
    "fixture_version": 1,
}
_SEARCH_FIXTURE = {
    "tool": "web.search",
    "match_mode": "subset",
    "match_arguments": {"query": "上海 天气"},
    "status": "success",
    "result": {"results": ["上海天气:多云 25℃"]},
    "fixture_id": "fx-s1",
    "fixture_version": 1,
}


class BigramEncoder:
    """内存等价检索编码器:字符二元组词袋向量,可重复、无外部服务。"""

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(text) for text in texts]

    @staticmethod
    def _vec(text: str) -> list[float]:
        vec = [0.0] * 4096
        cleaned = text.lower()
        for index in range(max(0, len(cleaned) - 1)):
            gram = cleaned[index : index + 2]
            slot = hash(gram) % 4096
            vec[slot] += 1.0
        return vec


class FakeChatModel:
    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self._index = 0

    def bind_tools(self, tools, **_kwargs):
        return self

    async def ainvoke(self, messages, **_kwargs):
        assert self._index < len(self._responses), "FakeChatModel 响应已耗尽"
        item = self._responses[self._index]
        self._index += 1
        return item

    async def astream(self, messages, **kwargs):
        yield await self.ainvoke(messages, **kwargs)


def _call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


# ── C1:all = 完整目录 − 排除项,不受场景标签影响 ─────────────────────────────


def test_all_equals_full_catalog_minus_exclusions():
    catalog, _ordered = build_template_catalog(_VISIBLE)
    loader = ToolLoader(catalog, tool_loading="all")
    names = [card.name for card in loader.load_for_turn("general")]
    assert names == sorted(set(_VISIBLE))  # 不含 search_tools,稳定排序
    # 场景标签不影响 all 装载(与 scoped 对照)
    assert [card.name for card in loader.load_for_turn("market")] == names
    assert [card.name for card in loader.load_for_turn("research")] == names


def test_all_applies_exclusions():
    catalog, _ = build_template_catalog(_VISIBLE)
    loader = ToolLoader(catalog, tool_loading="all", excluded_tools={"weather.get_forecast"})
    names = [card.name for card in loader.load_for_turn("general")]
    assert "weather.get_forecast" not in names
    assert names == sorted(set(_VISIBLE) - {"weather.get_forecast"})


def test_search_and_all_share_eligible_catalog():
    catalog, _ = build_template_catalog(_VISIBLE)
    all_loader = ToolLoader(catalog, tool_loading="all")
    search_loader = ToolLoader(catalog, tool_loading="search", encoder=BigramEncoder(), search_base="catalog")
    assert [card.name for card in search_loader.eligible_catalog()] == [card.name for card in all_loader.load_all()]
    assert search_loader.fallback_policy == "none"  # 新正式口径不回退


def test_scoped_capability_kept_but_formal_templates_never_use_it():
    catalog, _ = build_template_catalog(_VISIBLE)
    loader = ToolLoader(catalog, tool_loading="scoped")  # 内核仍支持场景装载
    assert loader.tool_loading == "scoped"
    for template in TEMPLATES.values():
        if template.classification == CLASSIFICATION_FORMAL:
            assert template.base_config.tool_delivery != "scoped", template.template_id


# ── C2/C3:搜索候选范围、排除不可见不可执行、记录与恢复 ──────────────────────


def _search_config(**overrides):
    base = TEMPLATES["tool-delivery-comparison"].base_config
    return base.with_overrides({"tool_delivery": "search", "tools.search_top_k": 3, **overrides})


@pytest.mark.asyncio
async def test_excluded_tool_not_in_search_results_nor_executed():
    record = await run_native_agent(
        run_config=_search_config(**{"tools.excluded_tools": ["weather.get_forecast"]}),
        message="查上海天气",
        visible_tools=_VISIBLE,
        llm=FakeChatModel(
            [
                _call(SEARCH_TOOLS_NAME, {"query": "天气 预报", "top_k": 3}, "c0"),
                _call("weather.get_forecast", {"location": "上海"}, "c1"),  # 已排除 → 拒绝
                AIMessage(content="抱歉,当前没有可用的天气工具。"),
            ]
        ),
        fixtures=[_SEARCH_FIXTURE],
        encoder=BigramEncoder(),
        timeout_seconds=30,
    )
    search_hits = {row["name"] for row in record.search_log[0]["candidates"]}
    assert "weather.get_forecast" not in search_hits
    assert any(row.get("audit_code") == "TOOL_NOT_VISIBLE" for row in record.audits)
    # 未装载工具被治理拒绝:保留 DENIED 行,无真实执行(可观测性设计 §12.3)
    denied = [row for row in record.tool_calls if row["toolName"] == "weather.get_forecast"]
    assert denied and all(row["status"] == "DENIED" and row["fixtureHit"] is False for row in denied)


@pytest.mark.asyncio
async def test_search_returns_ranked_candidates_then_loads_and_calls():
    record = await run_native_agent(
        run_config=_search_config(),
        message="查上海天气",
        visible_tools=_VISIBLE,
        llm=FakeChatModel(
            [
                _call(SEARCH_TOOLS_NAME, {"query": "查询天气 预报", "top_k": 3}, "c0"),
                _call("weather.get_forecast", {"location": "上海"}, "c1"),
                AIMessage(content="上海今天多云,25℃。"),
            ]
        ),
        fixtures=[_WEATHER_FIXTURE],
        encoder=BigramEncoder(),
        timeout_seconds=30,
    )
    log = record.search_log[0]
    assert log["base"] == "catalog"
    assert log["fallback"] is False and log["fallback_policy"] == "none"
    assert log["threshold"] is not None
    assert log["duration_ms"] >= 0
    ranked = log["candidates"]
    assert ranked, "检索必须返回候选"
    assert all("rank" in row and "score" in row and "description" in row for row in ranked)
    assert [row["rank"] for row in ranked] == list(range(1, len(ranked) + 1))
    assert any(row["name"] == "weather.get_forecast" for row in ranked)
    executed = [row for row in record.tool_calls if row["toolName"] == "weather.get_forecast"]
    assert executed and executed[0]["status"] == "SUCCESS" and executed[0]["fixtureHit"] is True
    # search 模式:第二轮才装载命中工具,当轮 Tool Schema 逐轮不同(设计 §5.3)
    schemas_by_round = [row["toolSchemas"] for row in record.model_calls]
    first_names = {spec["function"]["name"] for spec in schemas_by_round[0]}
    assert first_names == {"search_tools"}
    assert "weather.get_forecast" in {spec["function"]["name"] for spec in schemas_by_round[1]}
    assert record.eligible_catalog_hash
    assert record.tool_schema_hash


@pytest.mark.asyncio
async def test_tool_not_visible_then_recover_by_searching_again():
    record = await run_native_agent(
        run_config=_search_config(),
        message="查上海天气",
        visible_tools=_VISIBLE,
        llm=FakeChatModel(
            [
                _call("weather.get_forecast", {"location": "上海"}, "c1"),  # 未装载 → 拒绝
                _call(SEARCH_TOOLS_NAME, {"query": "查询天气", "top_k": 3}, "c2"),  # 再搜索恢复
                _call("weather.get_forecast", {"location": "上海"}, "c3"),
                AIMessage(content="上海今天多云,25℃。"),
            ]
        ),
        fixtures=[_WEATHER_FIXTURE],
        encoder=BigramEncoder(),
        timeout_seconds=30,
    )
    events = record.tool_not_visible_events
    assert events and events[0]["tool"] == "weather.get_forecast"
    assert events[0]["recovered"] is True  # 再次搜索装载后成功调用
    assert any(row["toolName"] == "weather.get_forecast" and row["status"] == "SUCCESS" for row in record.tool_calls)


# ── C3:三段(四类)错误归因 ─────────────────────────────────────────────────


def test_attribution_retrieval_selection_invocation_answer():
    acceptable = ("weather.get_forecast",)
    # 检索错误:可接受工具未进入候选
    row = attribute_search_run(
        acceptable_tools=acceptable,
        search_log=[{"candidates": [{"name": "calculator.evaluate"}]}],
        tool_calls=[{"tool": "calculator.evaluate", "status": "success"}],
        answer_ok=True,
    )
    assert row.retrieval_error and not row.selection_error
    # 选择错误:进入候选但模型未选
    row = attribute_search_run(
        acceptable_tools=acceptable,
        search_log=[{"candidates": [{"name": "weather.get_forecast"}, {"name": "web.search"}]}],
        tool_calls=[{"tool": "calculator.evaluate", "status": "success"}],
        answer_ok=True,
    )
    assert row.selection_error and not row.retrieval_error
    # 调用错误:工具正确但执行失败(参数/依赖/顺序)
    row = attribute_search_run(
        acceptable_tools=acceptable,
        search_log=[{"candidates": [{"name": "weather.get_forecast"}]}],
        tool_calls=[{"tool": "weather.get_forecast", "status": "error"}],
        answer_ok=True,
    )
    assert row.invocation_error
    # 最终回答错误:工具证据正确但回答不合格
    row = attribute_search_run(
        acceptable_tools=acceptable,
        search_log=[{"candidates": [{"name": "weather.get_forecast"}]}],
        tool_calls=[{"tool": "weather.get_forecast", "status": "success"}],
        answer_ok=False,
    )
    assert row.final_answer_error and not row.invocation_error


# ── C4:三种工具可用性条件 → 不同但正确的可接受结果 ──────────────────────────


def test_three_availability_conditions_different_expectations():
    full = acceptable_paths_for(list(_VISIBLE), WEATHER_AVAILABILITY_SPEC)
    assert full["expectation"] == "preferred"
    assert full["acceptable_calls"] == ["weather.get_forecast"]
    degraded = acceptable_paths_for(sorted(set(_VISIBLE) - {"weather.get_forecast"}), WEATHER_AVAILABILITY_SPEC)
    assert degraded["expectation"] == "degraded-alternative"
    assert degraded["acceptable_calls"] == ["web.search"]
    honest = acceptable_paths_for(
        sorted(set(_VISIBLE) - {"weather.get_forecast", "web.search"}), WEATHER_AVAILABILITY_SPEC
    )
    assert honest["expectation"] == "honest-limitation"
    assert honest["acceptable_calls"] == []


def test_judge_preferred_path():
    judgment = judge_tool_availability(
        eligible_catalog=list(_VISIBLE),
        spec=WEATHER_AVAILABILITY_SPEC,
        tool_calls=[{"tool": "weather.get_forecast", "status": "success"}],
        answer="上海今天多云,25℃。",
    )
    assert judgment["task_success"] and judgment["accepted_path"] == "preferred"


def test_judge_degraded_alternative():
    eligible = sorted(set(_VISIBLE) - {"weather.get_forecast"})
    judgment = judge_tool_availability(
        eligible_catalog=eligible,
        spec=WEATHER_AVAILABILITY_SPEC,
        tool_calls=[{"tool": "web.search", "status": "success"}],
        answer="根据公开检索:上海多云 25℃。",
    )
    assert judgment["task_success"] and judgment["accepted_path"] == "degraded-alternative"


def test_judge_honest_limitation():
    eligible = sorted(set(_VISIBLE) - {"weather.get_forecast", "web.search"})
    judgment = judge_tool_availability(
        eligible_catalog=eligible,
        spec=WEATHER_AVAILABILITY_SPEC,
        tool_calls=[],
        answer="当前工具目录中没有可用的天气或网页检索工具,无法获取实时天气。",
    )
    assert judgment["task_success"] and judgment["accepted_path"] == "honest-limitation"


def test_judge_fabrication_and_claims_fail():
    eligible = sorted(set(_VISIBLE) - {"weather.get_forecast", "web.search"})
    fabricated = judge_tool_availability(
        eligible_catalog=eligible,
        spec=WEATHER_AVAILABILITY_SPEC,
        tool_calls=[],
        answer="已查询到上海今天 25℃,晴。",
    )
    assert not fabricated["task_success"]
    assert fabricated["success_claimed_without_call"] or fabricated["fabrication_suspected"]
    # 首选可见时调用被排除的替代不替代首选
    preferred_visible = judge_tool_availability(
        eligible_catalog=list(_VISIBLE),
        spec=WEATHER_AVAILABILITY_SPEC,
        tool_calls=[],
        answer="无法查询。",
    )
    assert not preferred_visible["task_success"]


def test_excluded_tool_call_is_always_wrong():
    judgment = judge_tool_availability(
        eligible_catalog=sorted(set(_VISIBLE) - {"weather.get_forecast"}),
        spec=WEATHER_AVAILABILITY_SPEC,
        tool_calls=[{"tool": "weather.get_forecast", "status": "success"}],
        answer="上海 25℃。",
    )
    assert judgment["excluded_tool_called"] == ["weather.get_forecast"]
    assert not judgment["task_success"]


# ── 模板视角:all/search 两组同 eligible(excluded 一致) ─────────────────────


def test_tool_delivery_template_variants_share_exclusions():
    plan = plan_template_batch("tool-delivery-comparison", repeat_count=1)
    configs = {run.variant_label: run.run_config for run in plan.runs}
    assert set(configs) == {"all", "search"}
    assert configs["all"].tools.excluded_tools == configs["search"].tools.excluded_tools == ()
    assert configs["search"].tools.search_top_k == 3
    assert configs["all"].tools.search_top_k is None


def test_snapshot_catalog_rejects_unknown_names():
    from bdlh_runtime.experiments.tool_catalog_snapshot import ComparisonToolCatalogError, build_comparison_catalog

    with pytest.raises(ComparisonToolCatalogError):
        build_comparison_catalog(("not.a.tool",))


def test_plain_catalog_all_keeps_registration_order_excluded_sorted():
    catalog = ToolCatalog()
    for name in ("c.tool", "a.tool", "b.tool"):
        catalog.register(ToolCard(name=name, description=f"{name} 描述", parameters={}, required_scope=[]))
    loader = ToolLoader(catalog, tool_loading="all", excluded_tools={"b.tool"})
    assert [card.name for card in loader.load_all()] == ["a.tool", "c.tool"]
