"""Java Runtime Data Remote Store 契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bdlh_runtime.contracts.history import AnalysisHistoryRecord
from bdlh_runtime.runtime.remote_runtime_data import (
    RemoteAnalysisHistoryStore,
    RemoteChatSessionStore,
    RemoteRunRegistry,
    RuntimeDataClient,
)
from bdlh_runtime.runtime.run_registry import RunLocation


@dataclass
class _Response:
    status_code: int
    body: dict[str, Any] | list[dict[str, Any]] | None = None

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.body


def test_remote_run_registry_scopes_request_to_run_owner() -> None:
    calls: list[dict[str, Any]] = []

    def request(**kwargs):
        calls.append(kwargs)
        return _Response(200, {
            "runId": "run-1",
            "threadId": "thread-1",
            "checkpointId": "cp-1",
            "runtimePath": "legacy_root_graph",
        })

    registry = RemoteRunRegistry(RuntimeDataClient(
        base_url="http://java", internal_token="internal", request=request
    ))
    registry.register(RunLocation("run-1", "thread-1", "7", "cp-1"))
    location = registry.get("run-1", "7")

    assert location == RunLocation("run-1", "thread-1", "7", "cp-1")
    assert calls[0]["params"] == {"user_id": 7}
    assert calls[0]["headers"] == {"X-Internal-Token": "internal"}
    assert calls[1]["params"] == {"user_id": 7}


def test_remote_chat_delete_treats_204_as_success() -> None:
    def request(**kwargs):
        assert kwargs["method"] == "DELETE"
        return _Response(204)

    store = RemoteChatSessionStore(RuntimeDataClient(
        base_url="http://java", internal_token="internal", request=request
    ))

    assert store.delete("session-1", "7") is True


def test_remote_history_preserves_python_contract_payload() -> None:
    calls: list[dict[str, Any]] = []

    def request(**kwargs):
        calls.append(kwargs)
        return _Response(200, {})

    store = RemoteAnalysisHistoryStore(RuntimeDataClient(
        base_url="http://java", internal_token="internal", request=request
    ))
    record = AnalysisHistoryRecord(
        history_id="history-1",
        thread_id="thread-1",
        run_id="run-1",
        authenticated_user_id="7",
        status="SUCCESS",
        analysis_result={"summary": "ok"},
    )
    store.save(record)

    assert calls[0]["params"] == {"user_id": 7}
    assert calls[0]["json"]["payload"]["analysis_result"] == {"summary": "ok"}
