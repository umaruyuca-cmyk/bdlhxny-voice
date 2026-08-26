"""checkpoint 暂停与恢复：pause_check 写入书签，恢复时带上原问题。"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from bdlh_runtime.engine.contracts import InputEvent
from bdlh_runtime.engine.loop import AgentLoop
from bdlh_runtime.engine.runtime import EngineRuntime
from bdlh_runtime.tools.catalog import catalog_from_snapshot
from tests.engine.test_loop import FakeChatModel


class _OncePause:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, run_id: str) -> bool:
        del run_id
        self.calls += 1
        return self.calls == 1


@pytest.mark.asyncio
async def test_pause_writes_checkpoint_and_resume_continues(registry_snapshot) -> None:
    llm = FakeChatModel([AIMessage(content="已按你补充的信息继续。")])
    pause = _OncePause()
    runtime = EngineRuntime(
        AgentLoop(
            llm=llm,
            catalog=catalog_from_snapshot(registry_snapshot),
            executor=lambda name, arguments: {"tool": name, "args": arguments},
        ),
        pause_check=pause,
    )
    event = InputEvent(
        event_id="e1",
        user_id="user-1",
        session_id="s1",
        run_id="r-cp",
        message="请分析宁德时代",
    )
    paused = await runtime.run(event)
    assert paused.response.response_kind == "ASK_USER"
    assert paused.response.audit_codes == ["PAUSED_BY_USER"]
    assert paused.checkpoint is not None
    assert paused.checkpoint.original_message == "请分析宁德时代"

    resumed = await runtime.run(
        event.model_copy(update={"message": "补充：看估值"}),
        checkpoint=paused.checkpoint,
    )
    assert resumed.response.response_kind == "ANSWER"
    assert "继续" in resumed.response.message
    texts = [getattr(item, "content", "") for item in llm.seen[0] if isinstance(item, HumanMessage)]
    assert any("请分析宁德时代" in str(text) for text in texts)
    assert any("补充：看估值" in str(text) for text in texts)
