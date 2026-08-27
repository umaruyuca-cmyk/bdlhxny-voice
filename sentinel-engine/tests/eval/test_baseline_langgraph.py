"""LangGraph 官方 ReAct 对照组接线测试：ScriptedModel，无真实 LLM。

覆盖：ToolCard→StructuredTool 的 schema 投影与共用 executor 直连、
完整循环（发起调用→ToolNode 执行→直答）、步数耗尽降级、历史轮次剔除。
"""

from __future__ import annotations

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from bdlh_runtime.tools.catalog import ToolCard
from tests.eval.ab_eval import MockToolExecutor
from tests.eval.baseline_langgraph import card_to_tool, react_official_run


class ScriptedModel(BaseChatModel):
    """按序弹出预设 AIMessage；bind_tools 原样返回自身（create_react_agent 兼容）。"""

    _queue: list = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **_kwargs):  # noqa: ANN001, ANN202
        return self

    def _generate(self, messages, stop=None, run_manager=None, **_kwargs):  # noqa: ANN001, ANN202
        return ChatResult(generations=[ChatGeneration(message=self._queue.pop(0))])


def _quote_card() -> ToolCard:
    return ToolCard(
        name="market.get_realtime_quote",
        description="获取实时行情",
        parameters={
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    )


def _tool_call_msg() -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": "market.get_realtime_quote", "args": {"symbol": "300750"}, "id": "c1", "type": "tool_call"}
        ],
    )


@pytest.mark.asyncio
async def test_card_to_tool_executes_via_shared_executor():
    executor = MockToolExecutor()
    tool = card_to_tool(_quote_card(), executor)

    assert tool.name == "market.get_realtime_quote"
    result = await tool.ainvoke({"symbol": "300750"})

    assert result["symbol"] == "300750"
    assert result["price"] == 185.50
    assert executor.call_log == [("market.get_realtime_quote", {"symbol": "300750"})]


@pytest.mark.asyncio
async def test_react_run_full_cycle():
    model = ScriptedModel()
    model._queue = [_tool_call_msg(), AIMessage(content="现价 185.50")]
    executor = MockToolExecutor()

    result = await react_official_run(
        message="宁德时代现在什么价",
        history=[],
        all_cards=[_quote_card()],
        llm=model,
        executor=executor,
        system_prompt="你是金融分析助手",
    )

    assert result.error is None
    assert result.answer == "现价 185.50"
    assert result.attempted_tools == ["market.get_realtime_quote"]
    assert [name for name, _ in result.tool_calls] == ["market.get_realtime_quote"]
    assert result.rounds == 2


@pytest.mark.asyncio
async def test_react_run_recursion_exhaustion():
    model = ScriptedModel()
    model._queue = [_tool_call_msg() for _ in range(50)]
    executor = MockToolExecutor()

    result = await react_official_run(
        message="任何问题",
        history=[],
        all_cards=[_quote_card()],
        llm=model,
        executor=executor,
        system_prompt="你是金融分析助手",
        recursion_limit=6,
    )

    assert result.answer == "（步数耗尽）"
    assert result.error is None
    assert set(result.attempted_tools) == {"market.get_realtime_quote"}


@pytest.mark.asyncio
async def test_react_run_rounds_exclude_history():
    model = ScriptedModel()
    model._queue = [AIMessage(content="直接回答")]
    executor = MockToolExecutor()

    result = await react_official_run(
        message="它现在什么价",
        history=[
            {"role": "user", "content": "看看宁德时代"},
            {"role": "assistant", "content": "宁德时代代码300750。"},
        ],
        all_cards=[_quote_card()],
        llm=model,
        executor=executor,
        system_prompt="你是金融分析助手",
    )

    assert result.error is None
    assert result.answer == "直接回答"
    assert result.rounds == 1
    assert result.attempted_tools == []
