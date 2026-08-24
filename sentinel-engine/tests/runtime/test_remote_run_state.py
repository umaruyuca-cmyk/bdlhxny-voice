"""Java Data Plane Run Projection 翻译层必须透传 L0 checkpoint。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tests.cognitive.test_checkpoint_resume import (
    _CompleteDispatcher,
    _domain_orchestrator,
    _InvokeSelector,
    _OncePause,
)

from bdlh_runtime.api.checkpoint_persistence import extract_checkpoint
from bdlh_runtime.cognitive.contracts import CognitiveAction, CognitiveActionType, InputEvent
from bdlh_runtime.domains.contracts import DomainBudget, DomainOperation, DomainRequest
from bdlh_runtime.runtime.remote_run_state import JavaDataPlaneRunStateStore
from bdlh_runtime.runtime.remote_runtime_data import RuntimeDataClient


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


def _invoke_action_for(user_id: str) -> CognitiveAction:
    return CognitiveAction(
        action_type=CognitiveActionType.INVOKE_DOMAIN,
        reason_code="DOMAIN_READ",
        reason="Read the requested result",
        domain_request=DomainRequest(
            request_id="request-1",
            domain="example",
            authenticated_user_id=user_id,
            objective="Read a validated result",
            authorized_operations={DomainOperation.READ_PUBLIC_RESEARCH},
            budget=DomainBudget(tool_call_limit=1, runtime_seconds=5),
        ),
    )


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


async def test_java_store_roundtrip_resume_from_dispatch_does_not_reselect() -> None:
    selector = _InvokeSelector(_invoke_action_for("7"))
    dispatcher = _CompleteDispatcher()
    orchestrator = _domain_orchestrator(selector, dispatcher, _OncePause(after_calls=2))
    event = InputEvent(
        event_id="e1",
        run_id="r-dispatch-store",
        user_id="7",
        session_id="s1",
        message="hello",
    )
    paused = await orchestrator.run(event)
    assert paused.checkpoint is not None
    assert paused.checkpoint.resume_cursor == "dispatch"

    store = _store()
    store.save(event.run_id, event.user_id, _paused_state(paused, session_id=event.session_id))
    loaded = store.load(event.run_id, event.user_id)
    checkpoint = extract_checkpoint(loaded)

    assert loaded is not None
    assert loaded["checkpoint_id"] == paused.checkpoint.checkpoint_id
    assert checkpoint is not None
    assert checkpoint.resume_cursor == "dispatch"
    assert checkpoint.pending_action is not None

    resumed = await orchestrator.run(event, checkpoint=checkpoint)
    assert selector.calls == 1
    assert dispatcher.calls == 1
    assert resumed.state.domain_calls_used == 1
    assert resumed.response.response_kind == "DOMAIN_RESULT"


async def test_java_store_roundtrip_resume_from_after_domain_does_not_redispatch() -> None:
    selector = _InvokeSelector(_invoke_action_for("7"))
    dispatcher = _CompleteDispatcher()
    orchestrator = _domain_orchestrator(selector, dispatcher, _OncePause(after_calls=3))
    event = InputEvent(
        event_id="e1",
        run_id="r-after-store",
        user_id="7",
        session_id="s1",
        message="hello",
    )
    paused = await orchestrator.run(event)
    assert paused.checkpoint is not None
    assert paused.checkpoint.resume_cursor == "after_domain"

    store = _store()
    store.save(event.run_id, event.user_id, _paused_state(paused, session_id=event.session_id))
    loaded = store.load(event.run_id, event.user_id)
    checkpoint = extract_checkpoint(loaded)

    assert checkpoint is not None
    assert checkpoint.resume_cursor == "after_domain"
    assert checkpoint.last_outcome is not None

    resumed = await orchestrator.run(event, checkpoint=checkpoint)
    assert selector.calls == 1
    assert dispatcher.calls == 1
    assert resumed.state.domain_calls_used == 1
    assert resumed.response.response_kind == "DOMAIN_RESULT"
