"""Java Data Plane Run Projection 翻译层必须透传 L0 checkpoint。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage
from tests.engine.test_loop import FakeChatModel
from tests.helpers_registry import seeded_snapshot

from bdlh_runtime.api.checkpoint_persistence import extract_checkpoint
from bdlh_runtime.engine.contracts import InputEvent
from bdlh_runtime.engine.loop import AgentLoop
from bdlh_runtime.engine.runtime import EngineRuntime
from bdlh_runtime.infra.remote_run_state import JavaDataPlaneRunStateStore
from bdlh_runtime.infra.remote_runtime_data import RuntimeDataClient
from bdlh_runtime.tools.catalog import catalog_from_snapshot


@dataclass
class _Response:
    status_code: int
    body: dict[str, Any] | None = None

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any] | None:
        return self.body


class _FakeProjectionBackend:
    """模拟 Java PUT/GET /projection 的 camelCase JSON 往返。"""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    def request(self, **kwargs: Any) -> _Response:
        path = str(kwargs["path"])
        method = str(kwargs["method"])
        params = kwargs.get("params") or {}
        run_id = path.rstrip("/").split("/")[-2]
        user_id = str(params.get("user_id"))
        if method == "PUT":
            body = dict(kwargs.get("json") or {})
            body["_user_id"] = user_id
            self._rows[run_id] = body
            return _Response(200, self._response(run_id))
        stored = self._rows.get(run_id)
        if stored is None or stored.get("_user_id") != user_id:
            return _Response(404)
        return _Response(200, self._response(run_id))

    def _response(self, run_id: str) -> dict[str, Any]:
        row = self._rows[run_id]
        return {
            "runId": run_id,
            "threadId": row.get("threadId"),
            "status": row.get("status"),
            "nextStage": row.get("nextStage"),
            "finalResponse": row.get("finalResponse"),
            "interrupts": row.get("interrupts") or [],
            "events": row.get("events") or [],
            "checkpointId": row.get("checkpointId"),
            "cognitiveCheckpoint": row.get("cognitiveCheckpoint"),
        }


def _store() -> JavaDataPlaneRunStateStore:
    backend = _FakeProjectionBackend()
    return JavaDataPlaneRunStateStore(
        RuntimeDataClient(base_url="http://java-data", internal_token="token", request=backend.request)
    )


class _OncePause:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, run_id: str) -> bool:
        del run_id
        self.calls += 1
        return self.calls == 1


def _paused_state(execution, *, session_id: str) -> dict[str, Any]:
    checkpoint = execution.checkpoint
    assert checkpoint is not None
    return {
        "thread_id": session_id,
        "status": "PAUSED",
        "final_response": execution.response.model_dump(mode="json"),
        "events": [],
        "checkpoint_id": checkpoint.checkpoint_id,
        "cognitive_checkpoint": checkpoint.model_dump(mode="json"),
    }


async def test_java_store_roundtrip_resume_keeps_original_message() -> None:
    pause = _OncePause()
    runtime = EngineRuntime(
        AgentLoop(
            llm=FakeChatModel([AIMessage(content="已从书签继续")]),
            catalog=catalog_from_snapshot(seeded_snapshot()),
            executor=lambda name, arguments: {"tool": name, "args": arguments},
        ),
        pause_check=pause,
    )
    event = InputEvent(
        event_id="e1",
        run_id="r-dispatch-store",
        user_id="7",
        session_id="s1",
        message="hello analysis please continue later",
    )
    paused = await runtime.run(event)
    assert paused.checkpoint is not None

    store = _store()
    store.save(event.run_id, event.user_id, _paused_state(paused, session_id=event.session_id))
    loaded = store.load(event.run_id, event.user_id)
    checkpoint = extract_checkpoint(loaded)

    assert loaded is not None
    assert loaded["checkpoint_id"] == paused.checkpoint.checkpoint_id
    assert checkpoint is not None
    assert checkpoint.original_message == event.message

    resumed = await runtime.run(
        event.model_copy(update={"message": "继续"}),
        checkpoint=checkpoint,
    )
    assert resumed.response.response_kind == "ANSWER"
    assert "继续" in resumed.response.message
