from __future__ import annotations

import json
from pathlib import Path

import pytest

from bdlh_runtime.data_client import DataServiceError
from bdlh_runtime.memory import ActiveBuildConflict, BuildIdempotencyConflict, ContextBuildStore
from bdlh_runtime.memory.service import ContextWorkbenchService
from bdlh_runtime.memory.sources import DatabaseSessionSource, FrozenSessionSource, ShadowSessionSource, source_for_mode
from bdlh_runtime.memory.turns import events_with_turns
from bdlh_runtime.session import SessionCompiler
from bdlh_runtime.session.loader import SessionEvent


def test_turns_start_at_user_and_keep_tool_pair_in_same_turn() -> None:
    events = (
        SessionEvent(1, "u1", "", "user_message", "问题", "user"),
        SessionEvent(2, "a1", "", "assistant_message", "准备调用", "assistant"),
        SessionEvent(3, "c1", "", "tool_call", "", "assistant", call_id="call-1", tool_name="read"),
        SessionEvent(4, "r1", "", "tool_result", "结果", "tool", call_id="call-1", tool_name="read"),
        SessionEvent(5, "u2", "", "user_message", "追问", "user"),
    )

    payload = events_with_turns(events)

    assert [row["turn_id"] for row in payload] == [
        "turn-0001",
        "turn-0001",
        "turn-0001",
        "turn-0001",
        "turn-0002",
    ]


def test_store_enforces_idempotency_and_one_active_build(tmp_path: Path) -> None:
    store = ContextBuildStore(tmp_path)
    created, replay = store.create(
        owner_id="owner-1",
        session_id="session-1",
        current_request_event_id="event-1",
        algorithm="budgeted-hybrid-v1",
        idempotency_key="idem-key-0001",
        source_type="FROZEN_FILE",
    )
    same, replay = store.create(
        owner_id="owner-1",
        session_id="session-1",
        current_request_event_id="event-1",
        algorithm="budgeted-hybrid-v1",
        idempotency_key="idem-key-0001",
        source_type="FROZEN_FILE",
    )
    assert replay is True
    assert same["build_id"] == created["build_id"]

    with pytest.raises(BuildIdempotencyConflict):
        store.create(
            owner_id="owner-1",
            session_id="session-2",
            current_request_event_id="event-2",
            algorithm="budgeted-hybrid-v1",
            idempotency_key="idem-key-0001",
            source_type="FROZEN_FILE",
        )
    with pytest.raises(ActiveBuildConflict) as conflict:
        store.create(
            owner_id="owner-1",
            session_id="session-1",
            current_request_event_id="event-1",
            algorithm="budgeted-hybrid-v1",
            idempotency_key="idem-key-0002",
            source_type="FROZEN_FILE",
        )
    assert conflict.value.build_id == created["build_id"]


def test_store_marks_interrupted_build_failed_after_restart(tmp_path: Path) -> None:
    first = ContextBuildStore(tmp_path)
    created, _ = first.create(
        owner_id="owner-1",
        session_id="session-1",
        current_request_event_id="event-1",
        algorithm="budgeted-hybrid-v1",
        idempotency_key="idem-key-0001",
        source_type="FROZEN_FILE",
    )
    first.start_phase(created["build_id"], "LOAD_HISTORY")

    restarted = ContextBuildStore(tmp_path)
    row = restarted.get(created["build_id"], "owner-1")

    assert row["status"] == "FAILED"
    assert row["error_code"] == "PROCESS_RESTART"


def test_workbench_build_excludes_selected_current_request_from_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ContextBuildStore(tmp_path)
    service = ContextWorkbenchService(store)
    overview = service.overview("ctx-session-context-engine-debug-01")
    current_id = overview["default_current_request_event_id"]
    monkeypatch.setattr(SessionCompiler, "from_env", classmethod(lambda cls, **_: SessionCompiler()))
    created, replay = service.create_build(
        owner_id="owner-1",
        session_id="ctx-session-context-engine-debug-01",
        current_request_event_id=current_id,
        algorithm="budgeted-hybrid-v1",
        idempotency_key="idem-build-0001",
    )

    assert replay is False
    service.execute_build(created["build_id"], "owner-1")
    completed = store.get(created["build_id"], "owner-1")
    artifact = store.artifact(created["build_id"], "owner-1")

    assert completed["status"] == "COMPLETED"
    assert completed["current_phase"] == "COMPLETED"
    assert [step["phase"] for step in completed["steps"]] == [
        "LOAD_HISTORY",
        "CLASSIFY_AND_SELECT",
        "SUMMARIZE_HISTORY",
        "VALIDATE_AND_PERSIST",
        "ASSEMBLE_CONTEXT",
        "COMPLETED",
    ]
    assert current_id not in artifact["source_event_ids"]
    assert artifact["current_request_event_id"] == current_id
    assert completed["llm_usage"]["classification_calls"] == 0
    assert json.loads((tmp_path / "artifacts" / f"{completed['artifact_id']}.json").read_text(encoding="utf-8"))


def test_store_latest_for_session_returns_most_recent_and_isolates_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ContextBuildStore(tmp_path)
    service = ContextWorkbenchService(store)
    overview = service.overview("ctx-session-context-engine-debug-01")
    current_id = overview["default_current_request_event_id"]
    monkeypatch.setattr(SessionCompiler, "from_env", classmethod(lambda cls, **_: SessionCompiler()))
    first, _replay = service.create_build(
        owner_id="owner-1",
        session_id="ctx-session-context-engine-debug-01",
        current_request_event_id=current_id,
        algorithm="budgeted-hybrid-v1",
        idempotency_key="latest-build-0001",
    )
    # 第一个构建完成后才能创建第二个(单活跃约束)
    service.execute_build(first["build_id"], "owner-1")
    second, _replay2 = service.create_build(
        owner_id="owner-1",
        session_id="ctx-session-context-engine-debug-01",
        current_request_event_id=current_id,
        algorithm="budgeted-hybrid-v1",
        idempotency_key="latest-build-0002",
    )

    latest = store.latest_for_session("owner-1", "ctx-session-context-engine-debug-01")

    assert latest is not None
    assert latest["build_id"] == second["build_id"]
    assert latest["status"] == "PENDING"
    assert latest["current_request_event_id"] == current_id
    assert store.latest_for_session("owner-2", "ctx-session-context-engine-debug-01") is None
    assert store.latest_for_session("owner-1", "missing-session") is None


def test_workbench_accepts_database_compatible_session_source(tmp_path: Path) -> None:
    frozen = FrozenSessionSource()

    class DatabaseSource:
        source_type = "PRODUCTION_DB"

        def list_sessions(self) -> list[dict]:
            return frozen.list_sessions()

        def get_session(self, session_id: str):
            return frozen.get_session(session_id)

    service = ContextWorkbenchService(ContextBuildStore(tmp_path), source=DatabaseSource())

    overview = service.overview("ctx-session-context-engine-debug-01")

    assert overview["source_type"] == "PRODUCTION_DB"
    assert overview["default_current_request_event_id"]


class _ProductionSessionClient:
    def list_context_sessions(self, owner_id: str) -> list[dict]:
        assert owner_id == "10000000-0000-0000-0000-000000000001"
        return [
            {
                "sessionId": "production-session-1",
                "title": "生产上下文",
                "sourceType": "PRODUCTION_DB",
                "sourceHash": "sha256:production",
                "sourceVersion": 3,
                "eventCount": 3,
                "turnCount": 2,
                "userMessageCount": 2,
                "defaultCurrentRequestEventId": "event-3",
            }
        ]

    def get_context_session(self, owner_id: str, session_id: str) -> dict:
        assert owner_id == "10000000-0000-0000-0000-000000000001"
        assert session_id == "production-session-1"
        return {
            "sessionId": session_id,
            "title": "生产上下文",
            "sourceHash": "sha256:production",
            "sourceVersion": 3,
            "events": [
                {
                    "eventId": "event-1",
                    "sequence": 1,
                    "eventType": "user_message",
                    "role": "user",
                    "content": "先检查历史",
                    "occurredAt": "2026-08-30T08:00:00Z",
                },
                {
                    "eventId": "event-2",
                    "sequence": 2,
                    "eventType": "assistant_message",
                    "role": "assistant",
                    "content": "历史已检查",
                    "occurredAt": "2026-08-30T08:00:01Z",
                },
                {
                    "eventId": "event-3",
                    "sequence": 3,
                    "eventType": "user_message",
                    "role": "user",
                    "content": "生成当前上下文",
                    "occurredAt": "2026-08-30T08:00:02Z",
                },
            ],
        }


def test_database_session_source_maps_data_service_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    owner_id = "10000000-0000-0000-0000-000000000001"
    monkeypatch.setenv("CONTEXT_TARGET_TOKENS", "4096")
    source = DatabaseSessionSource(owner_id, client=_ProductionSessionClient())  # type: ignore[arg-type]

    summaries = source.list_sessions()
    session, variants = source.get_session("production-session-1")

    assert summaries[0]["session_id"] == "production-session-1"
    assert summaries[0]["default_current_request_event_id"] == "event-3"
    assert session.owner_id == owner_id
    assert session.current_question == "生成当前上下文"
    assert session.context_target_tokens == 4096
    assert variants["context_variants"][0]["strategy"] == "budgeted"


def test_shadow_source_falls_back_without_writing_frozen_data() -> None:
    class UnavailableSource:
        source_type = "PRODUCTION_DB"

        def list_sessions(self) -> list[dict]:
            raise DataServiceError("unavailable")

        def get_session(self, session_id: str):
            raise DataServiceError(session_id, status_code=404)

    shadow = ShadowSessionSource(UnavailableSource())

    assert shadow.list_sessions()
    session, _variants = shadow.get_session("ctx-session-context-engine-debug-01")
    assert session.session_id == "ctx-session-context-engine-debug-01"


def test_source_mode_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="unsupported CONTEXT_MEMORY_MODE"):
        source_for_mode("owner-1", mode="surprise")
