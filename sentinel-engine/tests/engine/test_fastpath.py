"""快路径分流：闲聊 / 禁止不进循环，未命中才进 AgentLoop。"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from bdlh_runtime.cognitive.contracts import InputEvent
from bdlh_runtime.cognitive.semantic_router import build_kernel_router
from bdlh_runtime.engine.loop import AgentLoop
from bdlh_runtime.engine.runtime import EngineRuntime
from bdlh_runtime.tools.catalog import catalog_from_snapshot
from tests.engine.test_loop import FakeChatModel
from tests.helpers_encoder import LexicalEncoder


def _event(message: str) -> InputEvent:
    return InputEvent(
        event_id="e1",
        user_id="user-1",
        session_id="s1",
        run_id="r1",
        message=message,
    )


def _runtime(registry_snapshot, responses: list[AIMessage] | None = None) -> EngineRuntime:
    llm = FakeChatModel(responses or [AIMessage(content="循环不该被快路径触发")])
    loop = AgentLoop(
        llm=llm,
        catalog=catalog_from_snapshot(registry_snapshot),
        executor=lambda name, arguments: {"tool": name, "args": arguments},
        router=build_kernel_router(encoder=LexicalEncoder()),
    )
    return EngineRuntime(loop)


@pytest.mark.asyncio
async def test_chitchat_skips_loop(registry_snapshot) -> None:
    execution = await _runtime(registry_snapshot).run(_event("你好"))
    assert execution.response.audit_codes == ["SEMANTIC_CHITCHAT"]
    assert execution.response.response_kind == "ANSWER"
    assert "你好" in execution.response.message or "任务" in execution.response.message
    assert "guardrail.blocked" not in execution.state.public_events


@pytest.mark.asyncio
async def test_forbidden_blocks_without_tools(registry_snapshot) -> None:
    execution = await _runtime(registry_snapshot).run(_event("帮我立刻下单买入"))
    assert execution.response.response_kind == "BLOCKED"
    assert execution.response.audit_codes == ["SEMANTIC_FORBIDDEN"]
    assert "guardrail.blocked" in execution.state.public_events
