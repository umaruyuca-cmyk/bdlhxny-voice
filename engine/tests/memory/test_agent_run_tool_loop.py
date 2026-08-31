"""工具循环 Agent 运行(P1 工具执行底座接入)的单元测试。

全部使用 FakeChatModel、会话内冻结 fixture 与内存 Store,不调用真实 LLM、
不触网、不访问生产系统。既有单次调用测试(test_agent_run.py)不受影响。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from bdlh_runtime.memory import ContextBuildStore
from bdlh_runtime.memory.agent_run import (
    AgentRunInvalid,
    ToolLoopAgentRunner,
    session_tool_fixtures,
)
from bdlh_runtime.memory.service import ContextWorkbenchService
from bdlh_runtime.session import SessionCompiler
from bdlh_runtime.session.loader import SessionCase, SessionEvent

OWNER = "10000000-0000-0000-0000-000000000001"


class FakeChatModel:
    """按序返回预设 AIMessage;记录每轮实际收到的消息。"""

    def __init__(self, responses: list[AIMessage], delay: float = 0.0) -> None:
        self._responses = list(responses)
        self._index = 0
        self.delay = delay
        self.seen: list[list[Any]] = []

    def bind_tools(self, tools, **_kwargs):
        return self

    async def ainvoke(self, messages, **_kwargs):
        if self.delay:
            await asyncio.sleep(self.delay)
        self.seen.append(list(messages))
        item = self._responses[self._index]
        self._index += 1
        return item

    async def astream(self, messages, **kwargs):
        yield await self.ainvoke(messages, **kwargs)


def _tool_call(name: str = "demo.echo", args: dict[str, Any] | None = None, call_id: str = "call-1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": dict(args or {"q": "hi"}), "id": call_id, "type": "tool_call"}],
    )


def _final(text: str = "最终回答") -> AIMessage:
    return AIMessage(content=text, usage_metadata={"input_tokens": 30, "output_tokens": 12, "total_tokens": 42})


def _session_case(session_id: str = "s1", *, with_tools: bool = True) -> SessionCase:
    events: tuple[SessionEvent, ...]
    if with_tools:
        events = (
            SessionEvent(1, "u1", "", "user_message", "历史问题", "user"),
            SessionEvent(
                2,
                "t-call-1",
                "",
                "tool_call",
                "",
                "assistant",
                call_id="c1",
                tool_name="demo.echo",
                arguments={"q": "hi"},
            ),
            SessionEvent(
                3,
                "t-res-1",
                "",
                "tool_result",
                '{"answer": "冻结结果"}',
                "tool",
                call_id="c1",
                status="SUCCESS",
            ),
            SessionEvent(4, "u-current", "", "user_message", "当前请求", "user"),
        )
    else:
        events = (
            SessionEvent(1, "u1", "", "user_message", "历史问题", "user"),
            SessionEvent(2, "a1", "", "assistant_message", "历史回答", "assistant"),
            SessionEvent(3, "u-current", "", "user_message", "当前请求", "user"),
        )
    return SessionCase(
        session_id=session_id,
        session_version=1,
        title="",
        owner_id=OWNER,
        fixture_set_id=None,
        tool_catalog_version=None,
        current_question="当前请求",
        visible_tools=("demo.echo",) if with_tools else (),
        context_target_tokens=8192,
        events=events,
        source_hash="sha256:case",
        source_path="",
    )


class _Source:
    source_type = "FROZEN_FILE"

    def __init__(self, case: SessionCase) -> None:
        self.case = case

    def list_sessions(self) -> list[dict]:
        return []

    def get_session(self, session_id: str):
        return self.case, {
            "context_variants": [
                {
                    "variant_id": "budgeted-session",
                    "strategy": "budgeted",
                    "strategy_version": "budgeted-hybrid-v1",
                    "token_budget": 8192,
                }
            ]
        }


ARTIFACT_MESSAGES = [
    {"role": "system", "content": "冻结系统规则"},
    {"role": "user", "content": "历史问题"},
    {"role": "assistant", "content": "历史回答"},
    {"role": "user", "content": "当前请求"},
]


def test_session_tool_fixtures_derivation_from_history_pairs() -> None:
    case = _session_case()
    fixtures = session_tool_fixtures(case.events)
    assert len(fixtures) == 1
    fixture = fixtures[0]
    assert fixture["tool"] == "demo.echo"
    assert fixture["match_mode"] == "subset"
    assert fixture["match_arguments"] == {"q": "hi"}
    assert fixture["status"] == "success"
    assert fixture["result"] == {"answer": "冻结结果"}
    assert fixture["fixture_id"] == "t-call-1"


def test_session_tool_fixtures_error_status_and_plain_text() -> None:
    events = (
        SessionEvent(
            1, "c1", "", "tool_call", "", "assistant", call_id="k1", tool_name="x.y", arguments={"a": 1}
        ),
        SessionEvent(
            2,
            "r1",
            "",
            "tool_result",
            "纯文本失败正文",
            "tool",
            call_id="k1",
            status="FAILED",
            error_code="BOOM",
        ),
    )
    fixtures = session_tool_fixtures(events)
    assert fixtures[0]["status"] == "error"
    assert fixtures[0]["result"] == {"value": "纯文本失败正文", "error_code": "BOOM"}


def test_session_tool_fixtures_ignores_orphan_results() -> None:
    events = (
        SessionEvent(1, "r-orphan", "", "tool_result", "{}", "tool", call_id="missing"),
    )
    assert session_tool_fixtures(events) == []


def test_tool_loop_runner_multi_turn_with_frozen_fixtures() -> None:
    llm = FakeChatModel([
        AIMessage(
            content="",
            usage_metadata={"input_tokens": 100, "output_tokens": 8, "total_tokens": 108},
            tool_calls=[{"name": "demo.echo", "args": {"q": "hi"}, "id": "call-1", "type": "tool_call"}],
        ),
        _final("基于冻结结果的回答"),
    ])
    runner = ToolLoopAgentRunner(llm=llm)
    result = runner.run_with_session(ARTIFACT_MESSAGES, session=_session_case())

    assert result.output == "基于冻结结果的回答"
    assert result.steps == 2
    assert result.stop_reason == "FINAL_ANSWER"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["tool"] == "demo.echo"
    # 逐轮 usage 汇总:100+30 输入,8+12 输出;不是估算
    assert result.input_tokens == 130
    assert result.output_tokens == 20
    assert result.estimated is False
    assert result.model


def test_tool_loop_runner_sends_artifact_messages_as_is() -> None:
    llm = FakeChatModel([_final()])
    runner = ToolLoopAgentRunner(llm=llm)
    runner.run_with_session(ARTIFACT_MESSAGES, session=_session_case())

    first_round = llm.seen[0]
    assert [type(m).__name__ for m in first_round] == ["SystemMessage", "HumanMessage", "AIMessage", "HumanMessage"]
    assert [m.content for m in first_round] == [row["content"] for row in ARTIFACT_MESSAGES]


def test_tool_loop_runner_estimates_when_usage_missing() -> None:
    llm = FakeChatModel([AIMessage(content="回答正文")])
    runner = ToolLoopAgentRunner(llm=llm)
    result = runner.run_with_session(ARTIFACT_MESSAGES, session=_session_case(with_tools=False))
    assert result.estimated is True
    assert result.input_tokens > 0
    assert result.output_tokens > 0
    assert result.steps == 1
    assert result.tool_calls == ()


def test_tool_loop_runner_unmatched_arguments_return_not_in_fixture() -> None:
    llm = FakeChatModel([
        _tool_call(args={"q": "完全不同的参数"}),
        _final("仍能继续回答"),
    ])
    runner = ToolLoopAgentRunner(llm=llm)
    result = runner.run_with_session(ARTIFACT_MESSAGES, session=_session_case())
    # 未命中冻结 fixture → NOT_IN_FIXTURE 错误负载回填,循环继续,不触网
    assert result.output == "仍能继续回答"
    assert result.steps == 2


def test_tool_loop_runner_requires_llm_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    runner = ToolLoopAgentRunner()
    with pytest.raises(AgentRunInvalid) as exc:
        runner.run_with_session(ARTIFACT_MESSAGES, session=_session_case())
    assert exc.value.code == "LLM_UNAVAILABLE"


def test_tool_loop_runner_timeout_circuit_breaker() -> None:
    llm = FakeChatModel([_final()], delay=0.2)
    runner = ToolLoopAgentRunner(llm=llm, timeout_seconds=0.05)
    with pytest.raises(AgentRunInvalid) as exc:
        runner.run_with_session(ARTIFACT_MESSAGES, session=_session_case())
    assert exc.value.code == "AGENT_RUN_TIMEOUT"


def test_tool_loop_runner_env_max_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_AGENT_MAX_STEPS", "1")
    llm = FakeChatModel([_tool_call(), _tool_call()])
    runner = ToolLoopAgentRunner(llm=llm)
    result = runner.run_with_session(ARTIFACT_MESSAGES, session=_session_case())
    assert result.stop_reason == "MAX_AGENT_STEPS"
    assert result.steps == 1


def _service_with_tool_loop(tmp_path: Path, runner: ToolLoopAgentRunner) -> tuple[ContextWorkbenchService, str]:
    SessionCompiler.from_env = classmethod(lambda cls, **_: SessionCompiler())
    service = ContextWorkbenchService(
        ContextBuildStore(tmp_path),
        source=_Source(_session_case()),
        agent_runner=runner,
    )
    build, _replay = service.store.create(
        owner_id=OWNER,
        session_id="s1",
        current_request_event_id="u-current",
        algorithm="budgeted-hybrid-v1",
        idempotency_key="tool-loop-0001",
        source_type="FROZEN_FILE",
    )
    service.execute_build(build["build_id"], OWNER)
    return service, build["build_id"]


def test_service_agent_run_end_to_end_with_tool_loop(tmp_path: Path) -> None:
    llm = FakeChatModel([
        AIMessage(
            content="",
            usage_metadata={"input_tokens": 50, "output_tokens": 6, "total_tokens": 56},
            tool_calls=[{"name": "demo.echo", "args": {"q": "hi"}, "id": "call-1", "type": "tool_call"}],
        ),
        _final("端到端回答"),
    ])
    runner = ToolLoopAgentRunner(llm=llm)
    service, build_id = _service_with_tool_loop(tmp_path, runner)

    service.start_agent_run(build_id, OWNER)
    service.execute_agent_run(build_id, OWNER)

    row = service.store.get(build_id, OWNER)
    run = row["agent_run"]
    usage = row["llm_usage"]
    assert run["status"] == "COMPLETED"
    assert run["output"] == "端到端回答"
    assert run["steps"] == 2
    assert run["stop_reason"] == "FINAL_ANSWER"
    assert len(run["tool_calls"]) == 1
    assert run["tool_calls"][0]["tool"] == "demo.echo"
    # 分项计量:Agent 模型往返与工具调用单独计数,压缩计量不受影响
    assert usage["agent_calls"] == 2
    assert usage["agent_tool_calls"] == 1
    assert usage["agent_input_tokens"] == 80
    assert usage["agent_output_tokens"] == 18
    assert "summary_calls" in usage
    assert usage["agent_model"]


def test_service_agent_run_tool_loop_failure_frozen_as_snapshot(tmp_path: Path) -> None:
    class ExplodingModel(FakeChatModel):
        async def ainvoke(self, messages, **_kwargs):
            raise RuntimeError("connection refused by peer")

    runner = ToolLoopAgentRunner(llm=ExplodingModel([]))
    service, build_id = _service_with_tool_loop(tmp_path, runner)

    service.start_agent_run(build_id, OWNER)
    service.execute_agent_run(build_id, OWNER)

    row = service.store.get(build_id, OWNER)
    assert row["agent_run"]["status"] == "FAILED"
    assert row["agent_run"]["error_code"] == "LLM_UNAVAILABLE"
    assert row["status"] == "COMPLETED"  # 构建不受运行失败影响
    assert "agent_calls" not in row["llm_usage"]


def test_service_falls_back_to_single_call_runner_contract(tmp_path: Path) -> None:
    """仅实现 run() 的运行器(既有单次调用契约)仍可注入使用。"""

    from bdlh_runtime.memory.agent_run import AgentRunResult

    class SingleCallRunner:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, messages):
            self.calls += 1
            return AgentRunResult(output="单次回答", model="fake", input_tokens=7, output_tokens=3)

    SessionCompiler.from_env = classmethod(lambda cls, **_: SessionCompiler())
    runner = SingleCallRunner()
    service = ContextWorkbenchService(
        ContextBuildStore(tmp_path),
        source=_Source(_session_case()),
        agent_runner=runner,
    )
    build, _ = service.store.create(
        owner_id=OWNER,
        session_id="s1",
        current_request_event_id="u-current",
        algorithm="budgeted-hybrid-v1",
        idempotency_key="single-call-0001",
        source_type="FROZEN_FILE",
    )
    service.execute_build(build["build_id"], OWNER)
    service.start_agent_run(build["build_id"], OWNER)
    service.execute_agent_run(build["build_id"], OWNER)

    row = service.store.get(build["build_id"], OWNER)
    assert runner.calls == 1
    assert row["agent_run"]["output"] == "单次回答"
    assert row["llm_usage"]["agent_calls"] == 1
    assert row["llm_usage"]["agent_tool_calls"] == 0
