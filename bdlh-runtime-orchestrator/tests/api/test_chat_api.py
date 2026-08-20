import json
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi.testclient import TestClient

from bdlh_runtime.api.routes import create_api_app
from bdlh_runtime.cognitive.contracts import (
    CognitiveState,
    InputEvent,
    PublicResponse,
)
from bdlh_runtime.cognitive.orchestrator import CognitiveExecution
from bdlh_runtime.config import Settings
from bdlh_runtime.runtime.application import create_application
from bdlh_runtime.runtime.runtime_path import COGNITIVE_RUNTIME_PATH
from tests.helpers_registry import seeded_snapshot

SECRET = "test-jwt-secret-with-at-least-thirty-two-bytes"


def _token(user_id: int) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )


def _headers(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id)}"}


def _events(response) -> list[dict]:
    return [json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: ")]


class KnowledgeCognitive:
    async def run(self, event: InputEvent, *, observer: Any = None) -> CognitiveExecution:
        del observer
        return CognitiveExecution(
            state=CognitiveState(event=event),
            response=PublicResponse(
                response_kind="ANSWER",
                response_structure="KNOWLEDGE",
                message="市盈率（PE）是股票价格与每股收益的比值。",
                audit_codes=["TEST_KNOWLEDGE"],
            ),
        )


class ClarifyingCognitive:
    async def run(self, event: InputEvent, *, observer: Any = None) -> CognitiveExecution:
        del observer
        asking = "分析" in event.message and "600000" not in event.message
        return CognitiveExecution(
            state=CognitiveState(event=event),
            response=PublicResponse(
                response_kind="ASK_USER" if asking else "ANSWER",
                response_structure="CLARIFICATION" if asking else "KNOWLEDGE",
                message="你想分析哪只股票？" if asking else "已完成对 600000 的分析。",
                next_steps=["请提供名称或代码"] if asking else [],
                audit_codes=["TEST_CLARIFY"],
            ),
        )


def _client(*, cognitive: Any | None = None) -> TestClient:
    application = create_application(
        Settings(environment="test", auth_required=True, jwt_secret=SECRET),
        registry_snapshot=seeded_snapshot(),
    )
    if cognitive is not None:
        application.cognitive_application = cognitive
    return TestClient(create_api_app(application))


def test_chat_stream_requires_auth_and_uses_cognitive_path():
    client = _client(cognitive=KnowledgeCognitive())

    unauthorized = client.post(
        "/api/v1/chat/stream",
        json={"message": "什么是市盈率？", "mode": "general"},
    )
    response = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"message": "什么是市盈率？", "mode": "general"},
    )
    events = _events(response)

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert events[0]["runtimePath"] == COGNITIVE_RUNTIME_PATH
    assert any(event.get("type") == "token" for event in events)
    assert events[-1]["type"] == "done"
    assert events[-1]["status"] == "COMPLETED"
    assert events[-1]["runtimePath"] == COGNITIVE_RUNTIME_PATH


def test_chat_clarification_resumes_the_same_cognitive_run():
    """澄清后纯代码回答经 Turn Router resume 同一 run（禁止盲目 sticky 以外的路径）。"""
    client = _client(cognitive=ClarifyingCognitive())
    first = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"message": "请做技术分析", "mode": "general"},
    )
    first_events = _events(first)
    first_run = next(event["runId"] for event in first_events if event["type"] == "agent_run")
    session_id = next(event["sessionId"] for event in first_events if event["type"] == "agent_run")

    assert first_events[-1]["status"] == "NEED_CLARIFICATION"
    assert first_events[0]["runtimePath"] == COGNITIVE_RUNTIME_PATH

    resumed = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"sessionId": session_id, "message": "600000", "mode": "general"},
    )
    resumed_events = _events(resumed)
    resumed_run = next(event["runId"] for event in resumed_events if event["type"] == "agent_run")

    assert resumed_run == first_run
    assert resumed_events[0].get("turnDecision") == "resume"
    assert resumed_events[0]["runtimePath"] == COGNITIVE_RUNTIME_PATH
    assert resumed_events[-1]["type"] == "done"
    assert resumed_events[-1]["status"] == "COMPLETED"


def test_conversations_are_user_scoped_regenerable_and_deletable():
    client = _client(cognitive=KnowledgeCognitive())
    created = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"message": "什么是市净率？", "mode": "general"},
    )
    session_id = next(event["sessionId"] for event in _events(created) if event["type"] == "agent_run")

    regenerated = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={
            "sessionId": session_id,
            "message": "什么是市净率？",
            "mode": "general",
            "regenerate": True,
        },
    )
    own_detail = client.get(f"/api/v1/conversations/{session_id}", headers=_headers(7))
    other_detail = client.get(f"/api/v1/conversations/{session_id}", headers=_headers(8))

    assert regenerated.status_code == 200
    assert [item["role"] for item in own_detail.json()["messages"]] == ["user", "assistant"]
    assert other_detail.status_code == 404
    assert client.get("/api/v1/conversations", headers=_headers(8)).json() == []

    deleted = client.delete(f"/api/v1/conversations/{session_id}", headers=_headers(7))
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/conversations/{session_id}", headers=_headers(7)).status_code == 404
