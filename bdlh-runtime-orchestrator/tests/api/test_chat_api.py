from datetime import datetime, timedelta, timezone
import json

import jwt
from fastapi.testclient import TestClient

from bdlh_runtime.api.routes import create_api_app
from bdlh_runtime.config import Settings
from bdlh_runtime.runtime.application import create_application
from tests.helpers_registry import seeded_snapshot
from bdlh_runtime.runtimes.langgraph.agents.direct_response_model import (
    DeterministicDirectResponseModel,
)
from bdlh_runtime.runtimes.langgraph.graphs.root_graph import build_root_graph


SECRET = "test-jwt-secret-with-at-least-thirty-two-bytes"


def _token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )


def _headers(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id)}"}


def _events(response) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def _client() -> TestClient:
    application = create_application(
        Settings(environment="development", auth_required=True, jwt_secret=SECRET),
        registry_snapshot=seeded_snapshot(),
    )
    # API 契约测试不连接外部 LLM/MCP，只验证 Root Graph 路由和恢复语义。
    application.graph = build_root_graph(
        registry_snapshot=seeded_snapshot(),
        direct_response_model=DeterministicDirectResponseModel()
    )
    return TestClient(create_api_app(application))


def test_chat_stream_requires_auth_and_uses_direct_response_without_tools():
    client = _client()

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
    assert any(event.get("type") == "token" for event in events)
    assert events[-1]["type"] == "done"
    assert events[-1]["status"] == "COMPLETED"


def test_chat_clarification_resumes_the_same_graph_run():
    client = _client()
    first = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"message": "请做技术分析", "mode": "general"},
    )
    first_events = _events(first)
    first_run = next(event["runId"] for event in first_events if event["type"] == "agent_run")
    session_id = next(event["sessionId"] for event in first_events if event["type"] == "agent_run")

    assert first_events[-1]["status"] == "NEED_CLARIFICATION"

    resumed = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"sessionId": session_id, "message": "600000", "mode": "general"},
    )
    resumed_events = _events(resumed)
    resumed_run = next(event["runId"] for event in resumed_events if event["type"] == "agent_run")

    assert resumed_run == first_run
    assert resumed_events[-1]["type"] == "done"
    assert resumed_events[-1]["status"] == "COMPLETED"


def test_conversations_are_user_scoped_regenerable_and_deletable():
    client = _client()
    created = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"message": "什么是市净率？", "mode": "general"},
    )
    session_id = next(
        event["sessionId"] for event in _events(created) if event["type"] == "agent_run"
    )

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
    own_detail = client.get(
        f"/api/v1/conversations/{session_id}", headers=_headers(7)
    )
    other_detail = client.get(
        f"/api/v1/conversations/{session_id}", headers=_headers(8)
    )

    assert regenerated.status_code == 200
    assert [item["role"] for item in own_detail.json()["messages"]] == ["user", "assistant"]
    assert other_detail.status_code == 404
    assert client.get("/api/v1/conversations", headers=_headers(8)).json() == []

    deleted = client.delete(
        f"/api/v1/conversations/{session_id}", headers=_headers(7)
    )
    assert deleted.status_code == 204
    assert client.get(
        f"/api/v1/conversations/{session_id}", headers=_headers(7)
    ).status_code == 404
