"""``AgentLoop.run(initial_messages=...)`` 冻结工件路径的单元测试。

覆盖:首轮消息原样发送、快路径不生效、工具轮回填、步数上限、不做循环内
refit。全部使用 FakeChatModel 与内存目录,不触网。
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from bdlh_runtime.engine.loop import (
    STOP_REASON_FINAL_ANSWER,
    STOP_REASON_MAX_AGENT_STEPS,
    AgentLoop,
    AgentTurn,
)
from bdlh_runtime.tools.catalog import ToolCard, ToolCatalog


class FakeChatModel:
    """按序返回预设 AIMessage;记录每轮收到的消息与绑定工具。"""

    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self._index = 0
        self.seen: list[list[Any]] = []
        self.bound_specs: list[list[dict[str, Any]]] = []

    def bind_tools(self, tools, **_kwargs):
        self.bound_specs.append(list(tools))
        return self

    async def ainvoke(self, messages, **_kwargs):
        self.seen.append(list(messages))
        item = self._responses[self._index]
        self._index += 1
        return item

    async def astream(self, messages, **kwargs):
        yield await self.ainvoke(messages, **kwargs)


async def _echo(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"tool": name, "args": arguments}


def _catalog(name: str = "demo.echo") -> ToolCatalog:
    catalog = ToolCatalog()
    catalog.register(
        ToolCard(
            name=name,
            description="回显参数",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            read_only=True,
            required_scope=[],
        )
    )
    return catalog


def _frozen_messages() -> list[Any]:
    return [
        SystemMessage(content="冻结系统规则"),
        HumanMessage(content="历史问题"),
        AIMessage(content="历史回答"),
        HumanMessage(content="当前请求"),
    ]


def _tool_call_message(name: str = "demo.echo") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": {"q": "hi"}, "id": "call-1", "type": "tool_call"}],
    )


class _RouterMustNotRun:
    """冻结工件路径不应触发快路径路由;触发即失败。"""

    def route(self, message: str) -> Any:
        raise AssertionError("frozen replay must not consult the fastpath router")


@pytest.mark.asyncio
async def test_initial_messages_sent_as_is_and_router_skipped() -> None:
    frozen = _frozen_messages()
    llm = FakeChatModel([AIMessage(content="直答")])
    loop = AgentLoop(llm=llm, catalog=_catalog(), executor=_echo, router=_RouterMustNotRun())
    result = await loop.run(
        AgentTurn(user_id="u1", message="被忽略的实时输入"),
        initial_messages=frozen,
    )
    assert result.answer == "直答"
    assert result.entered_loop is True
    assert result.stop_reason == STOP_REASON_FINAL_ANSWER
    # 首轮发送的就是冻结消息本身(逐字不变,系统提示未被重载)
    assert llm.seen[0] == frozen
    assert result.context_report is None
    assert result.context_build_result is None
    assert result.context_items_used == ()


@pytest.mark.asyncio
async def test_initial_messages_tool_round_feeds_back_observation() -> None:
    llm = FakeChatModel([_tool_call_message(), AIMessage(content="基于工具结果的回答")])
    loop = AgentLoop(llm=llm, catalog=_catalog(), executor=_echo, tool_loading="all")
    result = await loop.run(
        AgentTurn(user_id="u1", message=""),
        initial_messages=_frozen_messages(),
    )
    assert result.answer == "基于工具结果的回答"
    assert result.actual_steps == 2
    # 第二轮 = 冻结消息 + 工具调用消息 + 工具结果消息
    second_round = llm.seen[1]
    assert isinstance(second_round[-2], AIMessage) and second_round[-2].tool_calls
    assert isinstance(second_round[-1], ToolMessage)
    assert second_round[-1].tool_call_id == "call-1"
    assert len(second_round) == len(_frozen_messages()) + 2
    assert result.loaded_tools == ("demo.echo",)


@pytest.mark.asyncio
async def test_initial_messages_respects_max_agent_steps() -> None:
    llm = FakeChatModel([_tool_call_message(), _tool_call_message(), _tool_call_message()])
    loop = AgentLoop(llm=llm, catalog=_catalog(), executor=_echo, max_agent_steps=2)
    result = await loop.run(AgentTurn(user_id="u1", message=""), initial_messages=_frozen_messages())
    assert result.stop_reason == STOP_REASON_MAX_AGENT_STEPS
    assert result.actual_steps == 2
    assert len(llm.seen) == 2  # 未超额调用模型


@pytest.mark.asyncio
async def test_initial_messages_never_refits_frozen_prefix() -> None:
    """带预算也不重建:冻结工件是唯一事实源,增长由步数上限约束。"""

    llm = FakeChatModel([_tool_call_message(), AIMessage(content="完成")])
    loop = AgentLoop(llm=llm, catalog=_catalog(), executor=_echo)
    turn = AgentTurn(
        user_id="u1",
        message="",
        context_strategy="budgeted",
        token_budget=16,  # 极小预算:常规路径必然触发重建/失败
    )
    result = await loop.run(turn, initial_messages=_frozen_messages())
    assert result.stop_reason == STOP_REASON_FINAL_ANSWER
    assert result.context_rebuilds == 0
    assert result.context_error is None
    # 冻结前缀逐字保留(未被折叠或重排)
    assert llm.seen[1][: len(_frozen_messages())] == _frozen_messages()
