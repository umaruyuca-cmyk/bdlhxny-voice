"""Agent 运行(P1 切片)的单元测试:幂等、哈希校验、分项计量、失败收敛。

全部使用假运行器与内存/文件 Store,不调用真实 LLM。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bdlh_runtime.memory import ContextBuildStore
from bdlh_runtime.memory.agent_run import AgentRunInvalid, AgentRunResult, classify_agent_error
from bdlh_runtime.memory.service import ContextWorkbenchService
from bdlh_runtime.session import SessionCompiler

OWNER = "10000000-0000-0000-0000-000000000001"


class FakeRunner:
    """假 Agent 运行器:记录收到的消息,返回确定性输出。"""

    def __init__(self, output: str = "模型回答", fail: Exception | None = None) -> None:
        self.output = output
        self.fail = fail
        self.calls: list[list[dict[str, str]]] = []

    def run(self, messages: list[dict[str, str]]) -> AgentRunResult:
        if self.fail is not None:
            raise self.fail
        self.calls.append([dict(row) for row in messages])
        return AgentRunResult(
            output=self.output,
            model="fake-model",
            input_tokens=100,
            output_tokens=20,
            duration_ms=5,
        )


def _build_completed_service(tmp_path: Path, runner: FakeRunner) -> ContextWorkbenchService:
    """构造一个 legacy(file store)+ 已完成构建的服务实例。"""

    class _Source:
        source_type = "FROZEN_FILE"

        def list_sessions(self) -> list[dict]:
            return []

        def get_session(self, session_id: str):
            from bdlh_runtime.session.loader import SessionEvent

            events = (
                SessionEvent(1, "u1", "", "user_message", "历史问题", "user"),
                SessionEvent(2, "a1", "", "assistant_message", "历史回答", "assistant"),
                SessionEvent(3, "u-current", "", "user_message", "当前请求", "user"),
            )
            case = _session_case(session_id, events)
            variants = {
                "context_variants": [
                    {
                        "variant_id": "budgeted-session",
                        "strategy": "budgeted",
                        "strategy_version": "budgeted-hybrid-v1",
                        "token_budget": 8192,
                    }
                ]
            }
            return case, variants

    def _session_case(session_id: str, events: tuple) -> Any:
        from bdlh_runtime.session.loader import SessionCase

        return SessionCase(
            session_id=session_id,
            session_version=1,
            title="",
            owner_id=OWNER,
            fixture_set_id=None,
            tool_catalog_version=None,
            current_question=events[-1].content,
            visible_tools=(),
            context_target_tokens=8192,
            events=events,
            source_hash="sha256:case",
            source_path="",
        )

    SessionCompiler.from_env = classmethod(lambda cls, **_: SessionCompiler())
    service = ContextWorkbenchService(ContextBuildStore(tmp_path), source=_Source(), agent_runner=runner)
    build, _replay = service.store.create(
        owner_id=OWNER,
        session_id="s1",
        current_request_event_id="u-current",
        algorithm="budgeted-hybrid-v1",
        idempotency_key="agent-run-0001",
        source_type="FROZEN_FILE",
    )
    service.execute_build(build["build_id"], OWNER)
    return service, build["build_id"]


def test_agent_run_happy_path_records_output_and_separate_usage(tmp_path: Path) -> None:
    runner = FakeRunner(output="最终回答")
    service, build_id = _build_completed_service(tmp_path, runner)

    snapshot, started = service.start_agent_run(build_id, OWNER)
    service.execute_agent_run(build_id, OWNER)

    row = service.store.get(build_id, OWNER)
    usage = row["llm_usage"]
    assert started is True
    assert snapshot["status"] == "RUNNING"
    assert row["agent_run"]["status"] == "COMPLETED"
    assert row["agent_run"]["output"] == "最终回答"
    assert row["agent_run"]["message_hash_at_run"].startswith("sha256:")
    # 发送的就是冻结工件消息(原样,含系统与当前请求)
    assert len(runner.calls) == 1
    roles = [message["role"] for message in runner.calls[0]]
    assert roles[0] == "system" and roles[-1] == "user"
    # Agent 用量与压缩计量分开
    assert usage["agent_calls"] == 1
    assert usage["agent_input_tokens"] == 100
    assert usage["agent_output_tokens"] == 20
    assert usage["agent_model"] == "fake-model"


def test_agent_run_is_idempotent_one_click_one_run(tmp_path: Path) -> None:
    runner = FakeRunner()
    service, build_id = _build_completed_service(tmp_path, runner)
    service.start_agent_run(build_id, OWNER)
    service.execute_agent_run(build_id, OWNER)

    replay, started = service.start_agent_run(build_id, OWNER)

    assert started is False
    assert replay["status"] == "COMPLETED"
    assert len(runner.calls) == 1  # 没有第二次模型调用


def test_agent_run_rejects_active_duplicate(tmp_path: Path) -> None:
    runner = FakeRunner()
    service, build_id = _build_completed_service(tmp_path, runner)
    service.start_agent_run(build_id, OWNER)  # 处于 RUNNING

    with pytest.raises(AgentRunInvalid) as exc:
        service.start_agent_run(build_id, OWNER)
    assert exc.value.code == "AGENT_RUN_ALREADY_ACTIVE"
    service.execute_agent_run(build_id, OWNER)
    assert service.store.get(build_id, OWNER)["agent_run"]["status"] == "COMPLETED"


def test_agent_run_requires_completed_build(tmp_path: Path) -> None:
    runner = FakeRunner()
    service, build_id = _build_completed_service(tmp_path, runner)
    row = service.store._records[build_id]
    row["status"] = "FAILED"
    service.store._write(row)

    with pytest.raises(AgentRunInvalid) as exc:
        service.start_agent_run(build_id, OWNER)
    assert exc.value.code == "BUILD_NOT_COMPLETED"


def test_agent_run_failure_freezes_snapshot_build_stays_completed(tmp_path: Path) -> None:
    runner = FakeRunner(fail=RuntimeError("connection refused by peer"))
    service, build_id = _build_completed_service(tmp_path, runner)

    service.start_agent_run(build_id, OWNER)
    service.execute_agent_run(build_id, OWNER)

    row = service.store.get(build_id, OWNER)
    run = row["agent_run"]
    assert run["status"] == "FAILED"
    assert run["error_code"] == "LLM_UNAVAILABLE"
    assert run["error_message"]
    assert row["status"] == "COMPLETED"  # 构建不受运行失败影响
    assert "agent_calls" not in row["llm_usage"]  # 失败不计 Agent 调用


def test_agent_run_detects_artifact_mutation_mid_run(tmp_path: Path) -> None:
    runner = FakeRunner()
    service, build_id = _build_completed_service(tmp_path, runner)

    class TamperingRunner(FakeRunner):
        def run(self, messages: list[dict[str, str]]) -> AgentRunResult:
            result = super().run(messages)
            # 模拟运行期间工件被篡改:改写冻结文件里的第一条消息
            row = service.store.get(build_id, OWNER)
            path = Path(service.store.artifact_root) / f"{row['artifact_id']}.json"
            artifact = json.loads(path.read_text(encoding="utf-8"))
            artifact["messages"][0]["content"] = "被篡改的系统规则"
            path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
            return result

    service._agent_runner = TamperingRunner()
    service.start_agent_run(build_id, OWNER)
    service.execute_agent_run(build_id, OWNER)

    run = service.store.get(build_id, OWNER)["agent_run"]
    assert run["status"] == "FAILED"
    assert run["error_code"] == "ARTIFACT_INVALIDATED"


def test_classify_agent_error_codes() -> None:
    assert classify_agent_error(RuntimeError("request timed out")) == "LLM_TIMEOUT"
    assert classify_agent_error(RuntimeError("rate limit exceeded")) == "LLM_RATE_LIMITED"
    assert classify_agent_error(RuntimeError("insufficient quota")) == "LLM_QUOTA_EXHAUSTED"
    assert classify_agent_error(RuntimeError("boom")) == "LLM_UNAVAILABLE"
