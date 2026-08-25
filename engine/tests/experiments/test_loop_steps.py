"""max_agent_steps 口径测试:达到上限停止并记录原因,与重复次数无关。

FakeChatModel 构造「永远继续调用工具」与「立即给最终回答」两类模型行为;
不访问真实 LLM。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from bdlh_runtime.engine.loop import (
    STOP_REASON_FINAL_ANSWER,
    STOP_REASON_MAX_AGENT_STEPS,
    AgentLoop,
    AgentTurn,
)


class FakeChatModel:
    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self._index = 0
        self.calls = 0

    def bind_tools(self, tools, **_kwargs):
        return self

    async def ainvoke(self, messages, **_kwargs):
        self.calls += 1
        if self._index >= len(self._responses):
            raise AssertionError("FakeChatModel 响应已耗尽")
        item = self._responses[self._index]
        self._index += 1
        return item

    async def astream(self, messages, **kwargs):
        yield await self.ainvoke(messages, **kwargs)


def _tool_call(name: str = "file.search", call_id: str = "c1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": {"query": "x"}, "id": call_id, "type": "tool_call"}],
    )


def _loop(llm, registry_snapshot, *, max_agent_steps: int | None) -> AgentLoop:
    from bdlh_runtime.tools.catalog import catalog_from_snapshot

    return AgentLoop(
        llm=llm,
        catalog=catalog_from_snapshot(registry_snapshot),
        executor=_FrozenExecutor(),
        tool_loading="scoped",
        router=None,
        max_agent_steps=max_agent_steps,
    )


class _FrozenExecutor:
    async def __call__(self, name: str, arguments: dict):
        return {"tool": name, "simulated": True}


def _turn() -> AgentTurn:
    return AgentTurn(user_id="u1", message="帮我查一下仓库说明", scene_tag="research", run_id="r1")


async def test_max_agent_steps_stops_and_records_reason(registry_snapshot):
    """模型一直要调用工具:达到步数上限后停止,记录 stop_reason=MAX_AGENT_STEPS。"""
    llm = FakeChatModel([_tool_call(f"c{i}") for i in range(50)])
    loop = _loop(llm, registry_snapshot, max_agent_steps=3)
    result = await loop.run(_turn())
    assert result.stop_reason == STOP_REASON_MAX_AGENT_STEPS
    assert result.actual_steps == 3
    assert llm.calls == 3  # 3 步 = 3 次模型往返,没有额外轮次
    assert result.entered_loop


async def test_final_answer_stops_immediately(registry_snapshot):
    """得到最终回答后立即停止,不为达到上限继续调用。"""
    llm = FakeChatModel([AIMessage(content="仓库说明在 docs/README.md。")])
    loop = _loop(llm, registry_snapshot, max_agent_steps=5)
    result = await loop.run(_turn())
    assert result.stop_reason == STOP_REASON_FINAL_ANSWER
    assert result.actual_steps == 1
    assert llm.calls == 1


async def test_max_agent_steps_independent_of_repeat_count(registry_snapshot):
    """步数上限只约束单次运行;重复次数在实验层展开,不改变单次上限行为。"""
    for repeat_index in range(3):  # 模拟同一条件重复 3 次:每次独立、上限不变
        llm = FakeChatModel([_tool_call(f"c{i}") for i in range(50)])
        loop = _loop(llm, registry_snapshot, max_agent_steps=2)
        result = await loop.run(_turn())
        assert result.stop_reason == STOP_REASON_MAX_AGENT_STEPS
        assert result.actual_steps == 2
        assert llm.calls == 2
        assert repeat_index >= 0


async def test_legacy_max_tool_calls_unchanged(registry_snapshot):
    """未设置 max_agent_steps 时保持旧口径(max_tool_calls + 2),不破坏既有调用方。"""
    from bdlh_runtime.tools.catalog import catalog_from_snapshot

    llm = FakeChatModel([_tool_call(f"c{i}") for i in range(50)])
    loop = AgentLoop(
        llm=llm,
        catalog=catalog_from_snapshot(registry_snapshot),
        executor=_FrozenExecutor(),
        tool_loading="scoped",
        router=None,
        max_tool_calls=2,
    )
    result = await loop.run(_turn())
    assert result.actual_steps == 4  # 2 + 2 旧口径
    assert result.stop_reason == STOP_REASON_MAX_AGENT_STEPS
