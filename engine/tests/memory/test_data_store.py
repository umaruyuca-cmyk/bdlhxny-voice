from __future__ import annotations

import pytest

from bdlh_runtime.data_client import DataServiceError
from bdlh_runtime.memory import ActiveBuildConflict, BuildIdempotencyConflict, DataServiceContextBuildStore


class _BuildClient:
    def __init__(self) -> None:
        self.row: dict = {}
        self.artifact_payload: dict | None = None

    def create_context_workbench_build(self, payload: dict) -> dict:
        self.row = {
            "buildId": "20000000-0000-0000-0000-000000000001",
            "sessionId": payload["sessionId"],
            "currentRequestEventId": payload["currentRequestEventId"],
            "algorithmVersion": payload["algorithmVersion"],
            "status": "PENDING",
            "currentPhase": "LOAD_HISTORY",
            "steps": [],
            "budget": {},
            "itemCounts": {},
            "llmUsage": {},
            "warnings": [],
            "decisions": [],
        }
        return {"buildId": self.row["buildId"], "replay": False}

    def update_context_workbench_build(self, build_id: str, payload: dict) -> None:
        assert build_id == self.row["buildId"]
        self.row.update(payload)

    def get_context_workbench_build(self, owner_id: str, build_id: str) -> dict:
        assert owner_id == "owner-1"
        assert build_id == self.row["buildId"]
        result = dict(self.row)
        if self.artifact_payload is not None:
            result["artifactId"] = "30000000-0000-0000-0000-000000000001"
        return result

    def save_context_artifact(self, build_id: str, payload: dict) -> str:
        assert build_id == self.row["buildId"]
        self.artifact_payload = payload
        return "30000000-0000-0000-0000-000000000001"

    def get_context_artifact(self, owner_id: str, build_id: str) -> dict:
        assert owner_id == "owner-1"
        assert build_id == self.row["buildId"]
        assert self.artifact_payload is not None
        return {
            "artifactId": "30000000-0000-0000-0000-000000000001",
            "messages": self.artifact_payload["messages"],
            "contentHash": self.artifact_payload["contentHash"],
            "tokenCount": self.artifact_payload["tokenCount"],
            "tokenizerVersion": self.artifact_payload["tokenizerVersion"],
            "memorySegments": self.artifact_payload.get("memorySegments") or [],
        }

    def get_context_session(self, owner_id: str, session_id: str) -> dict:
        assert owner_id == "owner-1"
        return {
            "sessionId": session_id,
            "title": "生产会话",
            "sourceHash": "sha256:source",
            "sourceVersion": 1,
            "events": [
                {
                    "eventId": "event-1",
                    "sequence": 1,
                    "eventType": "user_message",
                    "role": "user",
                    "content": "历史问题",
                    "occurredAt": "2026-08-30T08:00:00Z",
                },
                {
                    "eventId": "event-2",
                    "sequence": 2,
                    "eventType": "assistant_message",
                    "role": "assistant",
                    "content": "历史回答",
                    "occurredAt": "2026-08-30T08:00:01Z",
                },
                {
                    "eventId": "event-3",
                    "sequence": 3,
                    "eventType": "user_message",
                    "role": "user",
                    "content": "当前问题",
                    "occurredAt": "2026-08-30T08:00:02Z",
                },
            ],
        }

    def get_latest_context_build(self, owner_id: str, session_id: str) -> dict | None:
        assert owner_id == "owner-1"
        assert session_id == self.row.get("sessionId")
        return {
            "buildId": self.row["buildId"],
            "sessionId": self.row.get("sessionId"),
            "currentRequestEventId": self.row.get("currentRequestEventId"),
            "algorithmVersion": self.row.get("algorithmVersion"),
            "status": "COMPLETED",
            "currentPhase": "COMPLETED",
            "errorCode": None,
            "createdAt": "2026-08-30T08:00:03Z",
            "updatedAt": "2026-08-30T08:00:04Z",
        }


def test_data_service_store_persists_phase_metrics_decisions_and_artifact() -> None:
    client = _BuildClient()
    store = DataServiceContextBuildStore("owner-1", client, source_type="PRODUCTION_DB")  # type: ignore[arg-type]
    created, replay = store.create(
        owner_id="owner-1",
        session_id="session-1",
        current_request_event_id="event-3",
        algorithm="budgeted-hybrid-v1",
        idempotency_key="idem-0001",
        source_type="PRODUCTION_DB",
    )

    store.start_phase(created["build_id"], "LOAD_HISTORY")
    store.finish_phase(created["build_id"], "LOAD_HISTORY", "SUCCEEDED", "HISTORY_LOADED")
    completed = store.complete(
        created["build_id"],
        budget={"context_budget_tokens": 4096},
        item_counts={"compressed": 1},
        llm_usage={"classification_calls": 0, "summary_calls": 1, "cache_hits": 0},
        warnings=[],
        decisions=[{"item_id": "event-1", "action": "compressed", "reason": "budget"}],
        artifact={
            "messages": [{"order": 0, "role": "system", "content": "规则"}],
            "message_hash": "sha256:artifact",
            "working_tokens": 120,
            "tokenizer_version": "tokenizer-v1",
        },
    )
    artifact = store.artifact(created["build_id"], "owner-1")

    assert replay is False
    assert completed["status"] == "COMPLETED"
    assert completed["llm_usage"]["summary_calls"] == 1
    assert artifact["current_request_event_id"] == "event-3"
    assert artifact["source_event_ids"] == ["event-1", "event-2"]
    assert artifact["message_hash"] == "sha256:artifact"
    # 无 Segment 的构建:明细字段回落为空,契约形状保持稳定
    assert artifact["memory_segments"] == []
    assert artifact["memory_segment_ids"] == []


def test_data_service_store_round_trips_artifact_segment_snapshot() -> None:
    client = _BuildClient()
    store = DataServiceContextBuildStore("owner-1", client, source_type="PRODUCTION_DB")  # type: ignore[arg-type]
    created, _replay = store.create(
        owner_id="owner-1",
        session_id="session-1",
        current_request_event_id="event-3",
        algorithm="budgeted-hybrid-v1",
        idempotency_key="idem-0002",
        source_type="PRODUCTION_DB",
    )
    segments = [
        {
            "segment_id": "seg-1",
            "turn_id": "turn-0001",
            "start_event_id": "event-1",
            "end_event_id": "event-2",
            "event_count": 2,
            "source_hash_short": "sha256:abc",
            "status": "FROZEN",
            "generation_mode": "LLM",
            "source_tokens": 120,
            "summary_tokens": 40,
            "cache_hit": True,
            "summary_excerpt": "轮摘要",
        }
    ]
    store.complete(
        created["build_id"],
        budget={},
        item_counts={},
        llm_usage={},
        warnings=[],
        decisions=[],
        artifact={
            "messages": [{"order": 0, "role": "system", "content": "规则"}],
            "message_hash": "sha256:artifact",
            "working_tokens": 100,
            "tokenizer_version": "tokenizer-v1",
            "memory_segments": segments,
        },
    )

    artifact = store.artifact(created["build_id"], "owner-1")

    # 保存载荷带上明细快照(写入 context_artifacts.memory_segments)
    assert client.artifact_payload["memorySegments"] == segments
    # 重读还原:明细与派生的 segment id 列表都完整
    assert artifact["memory_segments"] == segments
    assert artifact["memory_segment_ids"] == ["seg-1"]


def test_data_service_store_latest_for_session_returns_trimmed_row() -> None:
    client = _BuildClient()
    store = DataServiceContextBuildStore("owner-1", client, source_type="PRODUCTION_DB")  # type: ignore[arg-type]
    created, _replay = store.create(
        owner_id="owner-1",
        session_id="session-1",
        current_request_event_id="event-3",
        algorithm="budgeted-hybrid-v1",
        idempotency_key="idem-latest-001",
        source_type="PRODUCTION_DB",
    )

    latest = store.latest_for_session("owner-1", "session-1")

    assert latest == {
        "build_id": created["build_id"],
        "status": "COMPLETED",
        "current_phase": "COMPLETED",
        "current_request_event_id": "event-3",
        "algorithm_version": "budgeted-hybrid-v1",
        "error_code": None,
        "created_at": "2026-08-30T08:00:03Z",
        "updated_at": "2026-08-30T08:00:04Z",
    }

    class _NoBuildClient(_BuildClient):
        def get_latest_context_build(self, owner_id: str, session_id: str) -> dict | None:
            return None

    empty = DataServiceContextBuildStore("owner-1", _NoBuildClient(), source_type="PRODUCTION_DB")  # type: ignore[arg-type]
    assert empty.latest_for_session("owner-1", "session-1") is None


@pytest.mark.parametrize(
    ("code", "error_type"),
    [
        ("IDEMPOTENCY_KEY_REUSED", BuildIdempotencyConflict),
        ("ACTIVE_BUILD_EXISTS", ActiveBuildConflict),
    ],
)
def test_data_service_store_maps_conflicts(code: str, error_type: type[Exception]) -> None:
    class ConflictClient(_BuildClient):
        def create_context_workbench_build(self, payload: dict) -> dict:
            raise DataServiceError(
                code,
                status_code=409,
                payload={"errorCode": code, "activeBuildId": "active-1"},
            )

    store = DataServiceContextBuildStore(
        "owner-1",
        ConflictClient(),  # type: ignore[arg-type]
        source_type="PRODUCTION_DB",
    )

    with pytest.raises(error_type):
        store.create(
            owner_id="owner-1",
            session_id="session-1",
            current_request_event_id="event-3",
            algorithm="budgeted-hybrid-v1",
            idempotency_key="idem-0001",
            source_type="PRODUCTION_DB",
        )
