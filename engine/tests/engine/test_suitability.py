"""适合度：分析工具可调用；系统提示含不当结论红线；回复不得写成拍板结论。"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from bdlh_runtime.engine.contracts import InputEvent
from bdlh_runtime.engine.loop import AgentLoop, load_prompt
from bdlh_runtime.engine.runtime import EngineRuntime
from bdlh_runtime.tools.catalog import catalog_from_snapshot
from tests.engine.test_loop import FakeChatModel


def test_system_prompt_states_no_suitability_verdict() -> None:
    base = load_prompt("system_base.md")
    assert "不当确定性结论" in base or "红线" in base
    assert "一定合适" in base or "代替用户" in base


@pytest.mark.asyncio
async def test_analysis_tool_then_draft_disclosure(registry_snapshot) -> None:
    seen: list[tuple[str, dict]] = []

    async def executor(name: str, arguments: dict) -> dict:
        seen.append((name, arguments))
        return {
            "status": "SUCCESS",
            "conclusions": [{"text": "风险匹配筛查草稿"}],
            "limitations": ["本结果仅为筛查草稿，不构成代替用户决策的建议"],
        }

    llm = FakeChatModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "analysis.run_analysis",
                        "args": {},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="本结果仅为筛查草稿，不构成代替用户决策的建议。"),
        ]
    )
    runtime = EngineRuntime(
        AgentLoop(
            llm=llm,
            catalog=catalog_from_snapshot(registry_snapshot),
            executor=executor,
        )
    )
    execution = await runtime.run(
        InputEvent(
            event_id="e1",
            user_id="user-1",
            session_id="s1",
            run_id="r-suit",
            message="这个方案和我的约束条件匹配吗",
        )
    )
    assert seen and seen[0][0] == "analysis.run_analysis"
    assert "适合买入" not in execution.response.message
    assert "代替用户决策" in execution.response.message
    assert execution.response.response_kind == "ANSWER"
