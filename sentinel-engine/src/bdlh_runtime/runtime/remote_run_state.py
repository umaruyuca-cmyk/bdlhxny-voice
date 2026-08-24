"""Java Data Plane owned Cognitive Run Projection/Event adapter."""

from __future__ import annotations

import json
from typing import Any

from .remote_runtime_data import RuntimeDataClient
from .run_state import RunState


class JavaDataPlaneRunStateStore:
    """The only production Run State store.

    The Java API enforces the requested user scope on both reads and writes.
    Python only translates its API projection to the internal ``RunState`` form.
    """

    def __init__(self, client: RuntimeDataClient) -> None:
        self._client = client

    def save(self, run_id: str, user_id: str | None, state: RunState) -> None:
        events = state.get("events") or []
        payload_events = [
            {
                "eventType": str(event.get("event_type") or event.get("type") or "workflow"),
                "payload": event,
            }
            for event in events
            if isinstance(event, dict)
        ]
        self._client.call(
            "PUT",
            f"/internal/v1/runtime/runs/{run_id}/projection",
            user_id,
            payload={
                "threadId": str(state.get("thread_id") or run_id),
                "status": str(state.get("status") or "RUNNING"),
                "nextStage": state.get("next_stage"),
                "finalResponse": state.get("final_response"),
                "interrupts": state.get("__interrupt__") or [],
                "events": payload_events,
                "checkpointId": state.get("checkpoint_id"),
                "cognitiveCheckpoint": state.get("cognitive_checkpoint"),
            },
        )

    def load(self, run_id: str, user_id: str | None) -> RunState | None:
        data = self._client.call(
            "GET",
            f"/internal/v1/runtime/runs/{run_id}/projection",
            user_id,
            allow_not_found=True,
        )
        if data is None:
            return None
        events = [dict(event.get("payload") or {}) for event in data.get("events") or []]
        return {
            "run_id": str(data["runId"]),
            "thread_id": data.get("threadId"),
            "user_id": user_id,
            "status": data.get("status"),
            "next_stage": data.get("nextStage"),
            "final_response": data.get("finalResponse"),
            "__interrupt__": data.get("interrupts") or [],
            "events": events,
            "checkpoint_id": data.get("checkpointId"),
            "cognitive_checkpoint": _as_checkpoint_payload(data.get("cognitiveCheckpoint")),
        }


def _as_checkpoint_payload(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else None
    return None


def create_remote_run_state_store(*, base_url: str, internal_token: str | None) -> JavaDataPlaneRunStateStore:
    return JavaDataPlaneRunStateStore(RuntimeDataClient(base_url=base_url, internal_token=internal_token))
