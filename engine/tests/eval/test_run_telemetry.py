"""统一运行遥测契约:九类事件、工件分段、有效性分类与原生底座同口径记录。"""

from __future__ import annotations

import json
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

    def test_provider_402_balance_wording_is_invalid(self) -> None:
        """provider 实测文案(zhipu 402/code 30001):语序是 balance is insufficient。"""
        assert classify_failure(
            "Error code: 402 - {'code': 30001, 'message': 'Sorry, your account balance is insufficient', 'data': None}"
        ) == ("INVALID", "INSUFFICIENT_BALANCE")

    def test_service_unavailable_is_invalid(self) -> None:
        assert classify_failure("Connection error: connection refused") == ("INVALID", "MODEL_SERVICE_UNAVAILABLE")

    def test_chinese_timeout_is_model_service_unavailable(self) -> None:
        assert classify_failure("运行超时:单运行熔断") == ("INVALID", "MODEL_SERVICE_UNAVAILABLE")

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

    def test_integral_floats_serialized_language_neutrally(self) -> None:
        """整值浮点(如保留率 1.0)必须以整数形态进工件与哈希。

        Python "1.0" vs 发布器 JS "1" 会让 artifact_hash 跨语言复算不一致;
        构建时收敛后,工件 JSON 文本不出现 ":1.0" 形态。
        """
        recorder = _recorder()
        recorder.record_judgment({"required_retention_rate": 1.0, "ratio": 13 / 15})
        recorder.complete(status="COMPLETE")
        artifact = build_run_artifact(recorder.record)
        assert artifact["judgment"]["required_retention_rate"] == 1
        assert artifact["judgment"]["ratio"] == 13 / 15
        text = json.dumps(artifact, ensure_ascii=False)
        assert ": 1.0" not in text and ":1.0" not in text
        assert verify_artifact_hash(artifact)

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

    report = OutputGuardrail(checks=[C1ComplianceCheck(("买入", "卖出", "建议买入"))]).check("建议买入宁德时代", [])
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


# ── 可观测性快照(设计 §4/§5/§6):Schema 捕获/请求指纹/调用关联/事件锚点 ────


@pytest.mark.asyncio
async def test_recording_captures_bound_tool_schemas_and_param_states() -> None:
    """bind_tools 捕获当轮 Schema;参数三态逐调用盖章;请求指纹不只覆盖消息。"""
    from bdlh_runtime.evaluation.run_telemetry import REQUEST_SNAPSHOT_VERSION, payload_hash

    recorder = _recorder()
    recorder.attach_model_params(
        requested={"temperature": 0.1, "tool_choice": "auto"},
        sent={"temperature": 0.1, "max_output_tokens": 1200},
        unsupported={"tool_choice": "当前适配器未显式发送,由模型自行决定"},
    )
    specs = [
        {
            "type": "function",
            "function": {
                "name": "market.get_realtime_quote",
                "description": "读取实时行情",
                "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}},
            },
        }
    ]
    await (
        RecordingLLM(ScriptedToolModel(), recorder, "glm-4.7-flash")
        .bind_tools(specs)
        .ainvoke([SystemMessage(content="s"), HumanMessage(content="q")])
    )
    row = recorder.record.model_calls[0]
    assert row.tool_schemas == specs
    assert row.request_snapshot_version == REQUEST_SNAPSHOT_VERSION
    assert row.requested_params["temperature"] == 0.1
    assert row.sent_params["max_output_tokens"] == 1200
    assert row.unsupported_params["tool_choice"]
    # request_hash 覆盖 model+messages+tool_schemas+sent 参数,不等于消息哈希
    assert row.request_hash.startswith("sha256:")
    assert row.request_hash != payload_hash(row.messages)
    # 响应摘要:可观察决策 + 模型生成的 tool_calls(call_id)
    assert row.response_summary["decision"] == "call_tool"
    assert row.response_summary["toolCalls"][0]["callId"] == "c1"


def test_request_fingerprint_changes_when_schema_or_params_change() -> None:
    """消息、工具 Schema 或发送参数任一变化 → 指纹必须变化(设计 §4.3/§12.1)。"""
    from bdlh_runtime.evaluation.run_telemetry import request_fingerprint

    messages = [{"messageOrder": 0, "role": "user", "content": "q", "tokens": 1, "contentHash": "x"}]
    specs_a = [{"type": "function", "function": {"name": "a"}}]
    specs_b = [{"type": "function", "function": {"name": "b"}}]
    base = request_fingerprint(model="m", messages=messages, tool_schemas=specs_a, sent_params={"temperature": 0.1})
    assert base != request_fingerprint(
        model="m", messages=messages, tool_schemas=specs_b, sent_params={"temperature": 0.1}
    )
    assert base != request_fingerprint(
        model="m", messages=messages, tool_schemas=specs_a, sent_params={"temperature": 0.2}
    )
    assert base != request_fingerprint(
        model="other", messages=messages, tool_schemas=specs_a, sent_params={"temperature": 0.1}
    )
    # 全量相同 → 指纹稳定复算
    assert base == request_fingerprint(
        model="m", messages=messages, tool_schemas=specs_a, sent_params={"temperature": 0.1}
    )


class NotInFixtureExecutor:
    """返回 NOT_IN_FIXTURE 的执行器(未命中冻结数据)。"""

    async def __call__(self, name: str, arguments: dict) -> dict:
        return {"status": "error", "error_code": "NOT_IN_FIXTURE", "message": "no fixture", "simulated": True}


@pytest.mark.asyncio
async def test_tool_call_rows_link_model_call_and_mark_not_in_fixture() -> None:
    """工具行关联发起模型调用/call_id/事件序号;NOT_IN_FIXTURE → fixture_hit=false。"""
    from bdlh_runtime.evaluation.run_telemetry import EVENT_MODEL_REQUESTED, EVENT_MODEL_RESULT_APPENDED

    recorder = _recorder()
    bound = RecordingLLM(ScriptedToolModel(), recorder, "glm-4.7-flash").bind_tools([])
    await bound.ainvoke([HumanMessage(content="q")])
    await RecordingExecutor(NotInFixtureExecutor(), recorder)("market.get_realtime_quote", {"symbol": "300750"})
    row = recorder.record.tool_calls[0]
    assert row.fixture_hit is False
    assert row.status == "SUCCESS"  # 未命中冻结不冒充 FAILED;命中状态经 fixture_hit 区分
    assert row.model_call_sequence == 1
    assert row.call_id == "c1"
    assert row.requested_event_sequence is not None and row.completed_event_sequence is not None
    assert row.completed_event_sequence > row.requested_event_sequence
    # 事件锚点:model.requested 在每次模型调用前;result_appended 紧随 tool.completed
    event_types = [event["eventType"] for event in recorder.record.events]
    assert EVENT_MODEL_REQUESTED in event_types
    assert event_types[event_types.index(EVENT_TOOL_COMPLETED) + 1] == EVENT_MODEL_RESULT_APPENDED


def test_governance_denied_row_consumes_pending_call_pairing() -> None:
    """治理拦截行消费配对队列:call_id 归属发起模型调用,队列不泄漏。"""
    recorder = _recorder()
    audit = SimpleNamespace(
        caller="guest",
        tool_name="portfolio.get_current_positions",
        arguments_summary="{}",
        elapsed_ms=1,
        status="REJECTED",
        audit_code="G3-AUTH-001",
    )
    # 模拟模型已发起调用(工具未经执行器):直接登记最近模型调用序号并 stash 配对项
    recorder._last_model_sequence = 1
    recorder.stash_tool_call_ids([{"name": "portfolio.get_current_positions", "callId": "c9"}])
    record_governance_audits(recorder, [audit], [])
    denied = recorder.record.tool_calls[-1]
    assert denied.status == "DENIED"
    assert denied.fixture_hit is False
    assert denied.call_id == "c9"
    assert denied.model_call_sequence == 1
    assert recorder.pop_pending_tool_call("portfolio.get_current_positions") == {}
