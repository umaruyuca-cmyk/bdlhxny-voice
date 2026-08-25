"""Agent 循环与 scoped 装载单测（WO-T2-3）。

FakeChatModel 构造 tool_calls / 纯文本两类返回；覆盖 G-α 快路径、G-β 直答、
Observation 回填、历史裁剪、固定上下文注入、无 LLM degraded。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from bdlh_runtime.engine.loader import SCENE_TOOLSETS, ToolLoader
from bdlh_runtime.engine.loop import AgentLoop, AgentTurn, load_prompt
from bdlh_runtime.tools.catalog import catalog_from_snapshot


class FakeChatModel:
    """按序返回预设 AIMessage；bind_tools 记录装载集合。"""

    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self._index = 0
        self.bound_tools: list = []
        self.bind_history: list = []
        self.seen: list = []

    def bind_tools(self, tools, **_kwargs):
        snapshot = list(tools)
        self.bound_tools = snapshot
        self.bind_history.append(snapshot)
        return self

    async def ainvoke(self, messages, **_kwargs):
        self.seen.append(list(messages))
        if self._index >= len(self._responses):
            raise AssertionError("FakeChatModel 响应已耗尽")
        item = self._responses[self._index]
        self._index += 1
        return item

    async def astream(self, messages, **kwargs):
        yield await self.ainvoke(messages, **kwargs)


async def _echo(name: str, arguments: dict) -> dict:
    return {"tool": name, "args": arguments}


def _quote_call() -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "market.get_realtime_quote",
                "args": {"symbol": "300750"},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )


def test_scoped_mapping_core_is_general_only():
    """默认仅 general;垂直场景由场景包注入。"""
    from bdlh_runtime.scenarios import disable_all_scenario_packs

    disable_all_scenario_packs()
    assert set(SCENE_TOOLSETS) == {"general"}


def test_scoped_mapping_finance_pack_adds_vertical_scenes(finance_pack):
    assert {"market", "portfolio", "research", "watch", "general"} <= set(SCENE_TOOLSETS)


def test_load_scoped_market_excludes_portfolio(registry_snapshot, finance_pack):
    loader = ToolLoader(catalog_from_snapshot(registry_snapshot))
    names = {card.name for card in loader.load_scoped("market", authenticated=True)}
    assert "market.get_realtime_quote" in names
    assert "portfolio.get_current_positions" not in names
    assert "user.get_risk_profile" not in names


def test_load_scoped_portfolio_requires_auth(registry_snapshot, finance_pack):
    loader = ToolLoader(catalog_from_snapshot(registry_snapshot))
    guest = {card.name for card in loader.load_scoped("portfolio", authenticated=False)}
    host = {card.name for card in loader.load_scoped("portfolio", authenticated=True)}
    assert "portfolio.get_current_positions" not in guest
    assert "portfolio.get_current_positions" in host


def test_unknown_scene_falls_back_to_general(registry_snapshot):
    from bdlh_runtime.scenarios import disable_all_scenario_packs

    disable_all_scenario_packs()
    loader = ToolLoader(catalog_from_snapshot(registry_snapshot))
    fallback = {c.name for c in loader.load_scoped("unknown-scene", authenticated=False)}
    general = {c.name for c in loader.load_scoped("general", authenticated=False)}
    assert fallback == general
    assert "search_tools" not in general


def test_prompts_load_from_files_not_inline():
    base = load_prompt("system_base.md")
    chat = load_prompt("scene_chat.md")
    direct = load_prompt("scene_direct.md")
    assert "危险动作" in base or "红线" in base
    assert "G-β" in chat or "零工具" in chat
    assert "直答" in direct
    with pytest.raises(FileNotFoundError):
        load_prompt("does_not_exist.md")


@pytest.mark.asyncio
async def test_text_only_is_g_beta_zero_tools(registry_snapshot, finance_pack):
    llm = FakeChatModel([AIMessage(content="市盈率是价格相对盈利的倍数。")])
    loop = AgentLoop(llm=llm, catalog=catalog_from_snapshot(registry_snapshot), executor=_echo)
    result = await loop.run(AgentTurn(user_id="u1", message="什么是市盈率", scene_tag="research"))
    assert result.entered_loop is True
    assert result.answer == "市盈率是价格相对盈利的倍数。"
    assert result.audits == []
    assert llm.bound_tools
    assert "market.get_realtime_quote" in result.loaded_tools


@pytest.mark.asyncio
async def test_tool_calls_go_through_middleware_and_backfill(registry_snapshot, finance_pack):
    llm = FakeChatModel([_quote_call(), AIMessage(content="宁德时代最新价已从行情工具取得。")])
    loop = AgentLoop(llm=llm, catalog=catalog_from_snapshot(registry_snapshot), executor=_echo)
    result = await loop.run(AgentTurn(user_id="u1", message="宁德时代现在什么价", scene_tag="market", run_id="run-q"))
    assert result.entered_loop is True
    assert "行情工具" in result.answer
    assert result.audits[0].tool_name == "market.get_realtime_quote"
    assert result.audits[0].status == "SUCCESS"
    tool_messages = [m for m in result.messages if isinstance(m, ToolMessage)]
    assert tool_messages
    assert "300750" in tool_messages[0].content
    assert "source" in tool_messages[0].content
    assert len(llm.seen) == 2
    assert any(isinstance(m, ToolMessage) for m in llm.seen[1])


@pytest.mark.asyncio
async def test_history_trimmed_to_n_turns(registry_snapshot):
    history = []
    for i in range(12):
        history.append({"role": "user", "content": f"old-{i}"})
        history.append({"role": "assistant", "content": f"ans-{i}"})
    llm = FakeChatModel([AIMessage(content="ok")])
    loop = AgentLoop(
        llm=llm,
        catalog=catalog_from_snapshot(registry_snapshot),
        executor=_echo,
        session_history_turns=2,
    )
    await loop.run(AgentTurn(user_id="u1", message="now", history=history, scene_tag="general"))
    texts = []
    for msg in llm.seen[0]:
        if isinstance(msg, (HumanMessage, AIMessage)):
            texts.append(msg.content)
    assert "old-0" not in texts
    assert "old-10" in texts
    assert "now" in texts


@pytest.mark.asyncio
async def test_fixed_context_injected_via_builder(registry_snapshot):
    """任务二:固定上下文条目经 ContextBuilder 进入消息(不可信数据显式包裹)。"""
    llm = FakeChatModel([AIMessage(content="换房计划仍有效。")])
    loop = AgentLoop(llm=llm, catalog=catalog_from_snapshot(registry_snapshot), executor=_echo)
    result = await loop.run(
        AgentTurn(
            user_id="u1",
            message="对我的计划有影响吗",
            context_items=["两年内换房"],
        )
    )
    joined = "\n".join(m.content for m in llm.seen[0] if isinstance(m.content, str))
    assert "两年内换房" in joined
    assert "<untrusted-data>" in joined  # 不可信条目由构建器包裹
    assert result.context_report is not None
    assert result.context_report.required_retained


@pytest.mark.asyncio
async def test_no_llm_does_not_start_loop(registry_snapshot):
    loop = AgentLoop(llm=None, catalog=catalog_from_snapshot(registry_snapshot), executor=_echo)
    result = await loop.run(AgentTurn(user_id="u1", message="查一下天气"))
    assert result.degraded is True
    assert result.entered_loop is False
    assert result.answer == ""


@pytest.mark.asyncio
async def test_fastpath_chitchat_skips_loop(registry_snapshot):
    router = SimpleNamespace(route=lambda _m: SimpleNamespace(name="chitchat", response="你好，我在。"))
    llm = FakeChatModel([AIMessage(content="should-not-run")])
    called = {"n": 0}

    async def boom(_n, _a):
        called["n"] += 1
        return {}

    loop = AgentLoop(
        llm=llm,
        catalog=catalog_from_snapshot(registry_snapshot),
        executor=boom,
        router=router,
    )
    result = await loop.run(AgentTurn(user_id="u1", message="你好"))
    assert result.entered_loop is False
    assert result.fastpath_name == "chitchat"
    assert result.answer == "你好，我在。"
    assert called["n"] == 0
    assert llm.seen == []


@pytest.mark.asyncio
async def test_fastpath_knowledge_uses_direct_prompt(registry_snapshot):
    router = SimpleNamespace(route=lambda _m: SimpleNamespace(name="knowledge", response=None))
    llm = FakeChatModel([AIMessage(content="市盈率是估值指标。")])
    loop = AgentLoop(
        llm=llm,
        catalog=catalog_from_snapshot(registry_snapshot),
        executor=_echo,
        router=router,
    )
    result = await loop.run(AgentTurn(user_id="u1", message="什么是市盈率"))
    assert result.entered_loop is False
    assert result.fastpath_name == "knowledge"
    assert llm.bound_tools == []
    system = llm.seen[0][0]
    assert isinstance(system, SystemMessage)
    assert "直答" in system.content
