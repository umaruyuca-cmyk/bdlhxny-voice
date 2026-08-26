"""统一运行遥测契约:九类事件、工件分段、有效性分类与原生底座同口径记录。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from bdlh_runtime.engine.output_guardrail import C1ComplianceCheck, OutputGuardrail
from bdlh_runtime.evaluation.run_telemetry import (
    EVENT_GUARDRAIL_COMPLETED,
    EVENT_MODEL_COMPLETED,
    EVENT_RUN_STARTED,
    EVENT_TOOL_COMPLETED,
    EVENT_TOOL_REQUESTED,
    RUN_STATUS_INVALID,
    RecordingExecutor,
    RecordingLLM,
    RunRecorder,
    build_run_artifact,
    classify_failure,
    record_governance_audits,
    record_output_guardrail,
    snapshot_messages,
    validity_of,
    verify_artifact_hash,
)


def _recorder() -> RunRecorder:
    return RunRecorder(
        run_key="research-01:native-tool-calling:0",
        case_id="research-01",
        case_version=1,
        variant_id="default",
        snapshot_id="research-01:fixture-v1",
        snapshot_hash="sha256:snap",
        agent_mode="native-tool-calling",
        context_strategy="fixed-case-input",
        model="glm-4.7-flash",
        repeat_index=0,
        message="宁德时代现在什么价",
        category="金融研究",
    )


class TestClassifyFailure:
    def test_rate_limit_is_invalid(self) -> None:
        assert classify_failure("Error code: 429 - rate limit exceeded") == ("INVALID", "RATE_LIMITED")

    def test_balance_is_invalid(self) -> None:
        assert classify_failure("insufficient balance, please top up") == ("INVALID", "INSUFFICIENT_BALANCE")

    def test_service_unavailable_is_invalid(self) -> None:
        assert classify_failure("Connection error: connection refused") == ("INVALID", "MODEL_SERVICE_UNAVAILABLE")

    def test_task_failure_is_valid_but_failed(self) -> None:
        status, category = classify_failure("JSONDecodeError: expecting value")
        assert status == "FAILED"
        assert category == "AGENT_ERROR"
        assert validity_of(status) == "VALID"

    def test_no_error_is_complete(self) -> None:
        assert classify_failure(None) == ("COMPLETE", "")
        assert classify_failure("") == ("COMPLETE", "")


class TestArtifact:
    def test_nine_sections_and_hash_roundtrip(self) -> None:
        recorder = _recorder()
        recorder.record.judgment = {"tool_correct": True}
        recorder.complete(status="COMPLETE")
        artifact = build_run_artifact(recorder.record)
        expected_sections = {
            "artifact_version",
            "run_id",
            "batch_id",
            "status",
            "validity",
            "case",
            "experiment",
            "provenance",
            "context",
            "steps",
            "visible_tools",
            "guardrail_checks",
            "result",
            "judgment",
            "timing",
            "tokens",
            "artifact_hash",
        }
        assert set(artifact) == expected_sections
        assert verify_artifact_hash(artifact)

    def test_tampered_artifact_fails_hash(self) -> None:
        recorder = _recorder()
        recorder.complete(status="COMPLETE")
        artifact = build_run_artifact(recorder.record)
        artifact["status"] = "FAILED"
        assert not verify_artifact_hash(artifact)

    def test_invalid_run_keeps_validity_invalid(self) -> None:
        recorder = _recorder()
        recorder.complete(status=RUN_STATUS_INVALID, error_category="RATE_LIMITED", error_text="429")
        artifact = build_run_artifact(recorder.record)
        assert artifact["validity"] == "INVALID"
        assert verify_artifact_hash(artifact)


class TestMessageSnapshot:
    def test_roles_and_tool_call_rendering(self) -> None:
        messages = [
            SystemMessage(content="系统提示"),
            HumanMessage(content="宁德时代现在什么价"),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "market.get_realtime_quote", "args": {"symbol": "300750"}, "id": "c1", "type": "tool_call"}
                ],
            ),
            ToolMessage(content='{"price": 185.5}', tool_call_id="c1"),
        ]
        rows = snapshot_messages(messages)
        assert [row["role"] for row in rows] == ["system", "user", "assistant", "tool"]
        assert "market.get_realtime_quote" in rows[2]["content"]
        assert all(row["contentHash"].startswith("sha256:") for row in rows)


class ScriptedToolModel:
    """无状态金标模型:最后是用户消息则发起工具调用,是工具结果则给最终答案。"""

    def __init__(self, tool: str = "market.get_realtime_quote", arguments: dict | None = None) -> None:
        self.tool = tool
        self.arguments = arguments or {"symbol": "300750"}
        self.invocations: list[list[Any]] = []

    def bind_tools(self, tools: Any, **_kwargs: Any) -> ScriptedToolModel:
        return self

    async def ainvoke(self, messages: Any, **_kwargs: Any) -> AIMessage:
        self.invocations.append(list(messages))
        usage = {"token_usage": {"prompt_tokens": 120, "completion_tokens": 30}}
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content="宁德时代现价 185.50 元", response_metadata=usage)
        return AIMessage(
            content="",
            tool_calls=[{"name": self.tool, "args": self.arguments, "id": "c1", "type": "tool_call"}],
            response_metadata=usage,
        )


class RateLimitModel:
    """所有调用一律 429:验证三组执行器同口径判 INVALID。"""

    def bind_tools(self, tools: Any, **_kwargs: Any) -> RateLimitModel:
        return self

    async def ainvoke(self, messages: Any, **_kwargs: Any) -> AIMessage:
        raise RuntimeError("Error code: 429 - rate limit exceeded, please retry later")


class FrozenExecutor:
    def __init__(self) -> None:
        self.call_log: list[tuple[str, dict]] = []
        self.results: list[tuple[str, dict, dict]] = []

    async def __call__(self, name: str, arguments: dict) -> dict:
        self.call_log.append((name, dict(arguments)))
        result = {"symbol": "300750", "price": 185.50}
        self.results.append((name, dict(arguments), result))
        return result


@pytest.mark.asyncio
async def test_recording_wrappers_capture_calls_and_events() -> None:
    recorder = _recorder()
    model = RecordingLLM(ScriptedToolModel(), recorder, "glm-4.7-flash")
    executor = RecordingExecutor(FrozenExecutor(), recorder)
    bound = model.bind_tools([])
    first = await bound.ainvoke([SystemMessage(content="s"), HumanMessage(content="q")])
    await executor("market.get_realtime_quote", {"symbol": "300750"})
    await bound.ainvoke(
        [
            SystemMessage(content="s"),
            HumanMessage(content="q"),
            first,
            ToolMessage(content='{"price": 1}', tool_call_id="c1"),
        ]
    )

    assert [row.decision for row in recorder.record.model_calls] == ["call_tool", "answer"]
    assert [row.input_tokens for row in recorder.record.model_calls] == [120, 120]
    assert recorder.record.model_calls[0].messages[0]["role"] == "system"
    tool_rows = recorder.record.tool_calls
    assert len(tool_rows) == 1
    assert tool_rows[0].status == "SUCCESS"
    assert tool_rows[0].result_hash and tool_rows[0].arguments_hash
    event_types = [event["eventType"] for event in recorder.record.events]
    assert event_types[0] == EVENT_RUN_STARTED
    assert EVENT_MODEL_COMPLETED in event_types
    assert EVENT_TOOL_REQUESTED in event_types
    assert EVENT_TOOL_COMPLETED in event_types


@pytest.mark.asyncio
async def test_recording_llm_records_failed_call_category() -> None:
    recorder = _recorder()
    model = RecordingLLM(RateLimitModel(), recorder, "glm-4.7-flash")
    with pytest.raises(RuntimeError):
        await model.bind_tools([]).ainvoke([HumanMessage(content="q")])
    row = recorder.record.model_calls[0]
    assert row.status == "INVALID"
    assert row.error_category == "RATE_LIMITED"


def test_governance_audits_block_and_output_guardrail_rows() -> None:
    recorder = _recorder()
    audit = SimpleNamespace(
        caller="guest",
        tool_name="portfolio.get_current_positions",
        arguments_summary="{}",
        elapsed_ms=1,
        status="REJECTED",
        audit_code="G3-AUTH-001",
    )
    record_governance_audits(recorder, [audit], [])
    denied = recorder.record.tool_calls[-1]
    assert denied.status == "DENIED"
    assert denied.audit_code == "G3-AUTH-001"
    check = recorder.record.guardrail_checks[-1]
    assert check.stage == "action"
    assert check.decision == "block"

    report = OutputGuardrail(checks=[C1ComplianceCheck(("买入", "卖出", "建议买入"))]).check(
        "建议买入宁德时代", []
    )
    assert report.violations  # 危险执行语义命中
    record_output_guardrail(recorder, report)
    response_checks = [row for row in recorder.record.guardrail_checks if row.stage == "response"]
    assert response_checks
    assert all(row.decision == "modify" for row in response_checks)
    assert [event["eventType"] for event in recorder.record.events].count(EVENT_GUARDRAIL_COMPLETED) >= 2


def test_event_payload_keys_match_data_service_contract():
    """事件行键名必须与 data 服务 RunEventInput(camelCase)对齐。

    回归:此前 emit 用 event_type/occurred_at(snake_case),data 端 Jackson
    解析为 null → @NotBlank 校验 400,事件落库从未成功(run_events 恒 0 行)。
    """
    recorder = RunRecorder(
        run_key="k",
        case_id="c",
        case_version=1,
        variant_id="default",
        snapshot_id="s",
        snapshot_hash="h",
        agent_mode="native-tool-calling",
        context_strategy="fixed-case-input",
        model="m",
        repeat_index=0,
        message="hi",
        category="cat",
    )
    event = recorder.record.events[0]
    assert set(event) == {"sequence", "eventType", "payload", "occurredAt"}
    assert event["eventType"] == EVENT_RUN_STARTED
    assert isinstance(event["payload"], dict) and event["payload"]
    assert event["occurredAt"]
