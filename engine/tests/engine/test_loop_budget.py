"""loop 统一预算测试(修复"构建后才追加历史/Schema 不计预算/每轮不复查")。"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from bdlh_runtime.context import ConservativeTokenCounter, ContextBuilder, ContextWindowError
from bdlh_runtime.engine.loop import (
    AgentLoop,
    AgentTurn,
    assemble_model_context,
    load_prompt,
)
from bdlh_runtime.tools.catalog import ToolCard, ToolCatalog

_counter = ConservativeTokenCounter()


class FakeChatModel:
    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.seen: list[list[object]] = []

    def bind_tools(self, tools, **_kwargs):
        return self

    async def ainvoke(self, messages, **_kwargs):
        self.seen.append(list(messages))
        item = self._responses[self._index]
        self._index += 1
        return item

    async def astream(self, messages, **kwargs):
        yield await self.ainvoke(messages, **kwargs)


def _mini_catalog() -> ToolCatalog:
    catalog = ToolCatalog()
    catalog.register(
        ToolCard(
            name="demo.read",
            description="读取演示数据",
            parameters={
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
            },
            required_scope=[],
        )
    )
    return catalog


async def _blob_executor(name: str, arguments: dict) -> dict:
    return {"tool": name, "blob": "观测内容正文" * 60}


def _tool_call(index: int) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": "demo.read", "args": {"key": f"k{index}"}, "id": f"call-{index}", "type": "tool_call"}
        ],
    )


def test_history_and_question_are_counted_in_builder_budget() -> None:
    """历史与当前问题进入构建器:FULL 策略下超预算必须失败,而不是静默追加。"""

    history = [{"role": "user", "content": "很长的历史" * 100}]
    with pytest.raises(ContextWindowError):
        assemble_model_context(
            ContextBuilder(),
            system_prompt=load_prompt("system_base.md", "scene_chat.md"),
            turn=AgentTurn(user_id="u1", message="问题", history=history, context_strategy="full", token_budget=800),
        )


def test_history_and_question_keep_conversation_shape_after_build() -> None:
    """构建后历史保持消息角色与顺序,当前问题在最后,且计入 working_tokens。"""

    history = [
        {"role": "user", "content": "old-1"},
        {"role": "assistant", "content": "ans-1"},
    ]
    assembly = assemble_model_context(
        ContextBuilder(),
        system_prompt=load_prompt("system_base.md", "scene_chat.md"),
        turn=AgentTurn(user_id="u1", message="now", history=history, context_strategy="full"),
    )
    roles = [type(message).__name__ for message in assembly.messages]
    assert roles[0] == "SystemMessage"
    assert roles[-3:] == ["HumanMessage", "AIMessage", "HumanMessage"]
    assert assembly.messages[-3].content == "old-1"
    assert assembly.messages[-1].content == "now"
    joined = "\n".join(str(getattr(m, "content", "")) for m in assembly.messages)
    assert "[context item=" not in joined.split("old-1")[-1]  # 对话条目不加 item 头
    assert assembly.report.working_tokens >= 700


def test_tool_schema_reservation_shrinks_builder_budget() -> None:
    """Schema 预算预留:同样的 token_budget,Schema 越大可用构建预算越小。"""

    turn = AgentTurn(user_id="u1", message="问题", context_strategy="full", token_budget=900)
    prompt = load_prompt("system_base.md", "scene_chat.md")
    assembly = assemble_model_context(
        ContextBuilder(), system_prompt=prompt, turn=turn, tool_schema_tokens=0
    )
    assert assembly.report.budget_fit
    with pytest.raises(ContextWindowError):
        assemble_model_context(
            ContextBuilder(), system_prompt=prompt, turn=turn, tool_schema_tokens=200
        )


@pytest.mark.asyncio
async def test_per_round_refit_folds_older_tool_rounds_within_budget() -> None:
    """工具结果逐轮增长超出预算时:折叠更早轮重新压缩,最近两轮原文保留配对。"""

    catalog = _mini_catalog()
    from bdlh_runtime.engine.loop import _tool_schema_tokens

    schema_tokens = _tool_schema_tokens(catalog.list(), _counter)
    responses = [_tool_call(1), _tool_call(2), _tool_call(3), _tool_call(4), AIMessage(content="完成")]

    # 干跑(无界预算)取得各段规模,据此设定"恰好容纳 base+前三轮"的预算
    dry = AgentLoop(llm=FakeChatModel(list(responses)), catalog=catalog, executor=_blob_executor)
    dry_result = await dry.run(
        AgentTurn(user_id="u1", message="请检查", scene_tag="research", context_strategy="budgeted")
    )
    messages = dry_result.messages
    tool_indexes = [i for i, m in enumerate(messages) if isinstance(m, AIMessage) and m.tool_calls]
    first_tool = tool_indexes[0]
    base_tokens = sum(_counter.count(str(m.content)) for m in messages[:first_tool])
    round_tokens = []
    cursor = first_tool
    for boundary in tool_indexes[1:] + [len(messages)]:
        round_tokens.append(sum(_counter.count(str(m.content)) for m in messages[cursor:boundary]))
        cursor = boundary
    # round_tokens = [R1..R4];预算放行前三轮,第四轮后的最终调用触发折叠
    budget = base_tokens + round_tokens[0] + round_tokens[1] + round_tokens[2] + 10 + schema_tokens

    loop = AgentLoop(
        llm=FakeChatModel(list(responses)), catalog=catalog, executor=_blob_executor
    )
    result = await loop.run(
        AgentTurn(
            user_id="u1",
            message="请检查",
            scene_tag="research",
            context_strategy="budgeted",
            token_budget=budget,
        )
    )
    assert result.degraded is False, result.context_error
    assert result.answer == "完成"
    assert result.context_rebuilds >= 1
    joined = "\n".join(str(getattr(m, "content", "")) for m in result.messages)
    assert "tool-round-0" in joined  # 最早的轮被折叠为数据条目重新过构建器

    # 最近两轮保持原始消息对象:每个 ToolMessage 紧跟携带对应 tool_call 的 AIMessage
    for index, message in enumerate(result.messages):
        if isinstance(message, ToolMessage):
            previous = result.messages[index - 1]
            assert isinstance(previous, AIMessage)
            call_ids = {call["id"] for call in previous.tool_calls}
            assert message.tool_call_id in call_ids

    # 重建后总输入仍受预算约束(按保守计数口径;effective = 预算 - Schema 预留)
    effective = budget - schema_tokens
    total = sum(_counter.count(str(getattr(m, "content", ""))) for m in result.messages)
    assert total <= effective


@pytest.mark.asyncio
async def test_refit_without_foldable_rounds_fails_honestly() -> None:
    """预算放不下基座+当前轮(无可折叠轮)时诚实失败,不静默截断。"""

    from bdlh_runtime.engine.loop import _tool_schema_tokens

    catalog = _mini_catalog()
    responses = [_tool_call(1), AIMessage(content="完成")]
    schema_tokens = _tool_schema_tokens(catalog.list(), _counter)
    dry = AgentLoop(llm=FakeChatModel(list(responses)), catalog=catalog, executor=_blob_executor)
    dry_result = await dry.run(
        AgentTurn(user_id="u1", message="请检查", scene_tag="research", context_strategy="budgeted")
    )
    messages = dry_result.messages
    first_tool = next(i for i, m in enumerate(messages) if isinstance(m, AIMessage) and m.tool_calls)
    base_tokens = sum(_counter.count(str(m.content)) for m in messages[:first_tool])
    budget = base_tokens + schema_tokens + 5  # 初始构建恰好可行,第一轮工具结果必然超预算

    loop = AgentLoop(llm=FakeChatModel(list(responses)), catalog=catalog, executor=_blob_executor)
    result = await loop.run(
        AgentTurn(
            user_id="u1",
            message="请检查",
            scene_tag="research",
            context_strategy="budgeted",
            token_budget=budget,
        )
    )
    assert result.degraded is True
    # 诚实失败:要么无可退让(required 超预算),要么重建后仍超窗口
    assert result.context_error and "context needs" in result.context_error
    assert result.entered_loop is True
