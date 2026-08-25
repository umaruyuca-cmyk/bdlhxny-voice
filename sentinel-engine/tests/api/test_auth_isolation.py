from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient

from bdlh_runtime.api.routes import create_api_app
from bdlh_runtime.cognitive.contracts import CognitiveExecution, CognitiveState, InputEvent, PublicResponse
from bdlh_runtime.config import Settings
from tests.helpers_application import build_isolated_application

SECRET = "test-jwt-secret-with-at-least-thirty-two-bytes"


class _GuestCognitive:
    async def run(self, event: InputEvent, **_kwargs: object) -> CognitiveExecution:
        return CognitiveExecution(
            state=CognitiveState(event=event),
            response=PublicResponse(
                response_kind="ANSWER",
                response_structure="KNOWLEDGE",
                message="guest-ok",
                audit_codes=["GUEST_OK"],
            ),
        )


def _token(user_id: int, *, expired: bool = False) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "exp": now - timedelta(minutes=1) if expired else now + timedelta(hours=1),
        },
        SECRET,
        algorithm="HS256",
    )


def _client():
    application = build_isolated_application(
        settings=Settings(auth_required=True, jwt_secret=SECRET),
    )
    return application, TestClient(create_api_app(application))


def test_agent_runs_allow_guest_but_reject_invalid_jwt():
    """缺 Token → 游客可对话；伪造/过期 Token 仍 401。"""
    _, client = _client()

    guest = client.post("/api/v1/agent-runs", json={"message": "什么是市盈率？"})
    expired = client.post(
        "/api/v1/agent-runs",
        headers={"Authorization": f"Bearer {_token(7, expired=True)}"},
        json={"message": "什么是市盈率？"},
    )

    assert guest.status_code == 200
    assert guest.json()["run_id"]
    assert expired.status_code == 401


def test_chat_stream_allows_guest_without_login():
    application = build_isolated_application(
        settings=Settings(auth_required=True, jwt_secret=SECRET),
        cognitive_application=_GuestCognitive(),
    )
    client = TestClient(create_api_app(application))
    response = client.post(
        "/api/v1/chat/stream",
        json={"message": "你好", "enabledSkillIds": []},
    )
    assert response.status_code == 200
    assert "data:" in response.text


def test_jwt_subject_overrides_untrusted_payload_user_id():
    _, client = _client()

    response = client.post(
        "/api/v1/agent-runs",
        headers={"Authorization": f"Bearer {_token(7)}"},
        json={"message": "什么是市盈率？", "user_id": "8"},
    )

    assert response.status_code == 403


def test_users_with_the_same_public_thread_are_isolated_and_cannot_cross_read():
    application, client = _client()
    common_thread = "shared-browser-thread"

    first = client.post(
        "/api/v1/agent-runs",
        headers={"Authorization": f"Bearer {_token(7)}"},
        json={"message": "什么是市盈率？", "thread_id": common_thread},
    )
    second = client.post(
        "/api/v1/agent-runs",
        headers={"Authorization": f"Bearer {_token(8)}"},
        json={"message": "什么是市净率？", "thread_id": common_thread},
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["thread_id"] == second.json()["thread_id"] == common_thread
    first_location = application.run_registry.get(first.json()["run_id"])
    second_location = application.run_registry.get(second.json()["run_id"])
    assert first_location.thread_id == common_thread
    assert second_location.thread_id == common_thread
    assert first_location.user_id == "7"
    assert second_location.user_id == "8"

    own = client.get(
        f"/api/v1/agent-runs/{first.json()['run_id']}",
        headers={"Authorization": f"Bearer {_token(7)}"},
    )
    cross = client.get(
        f"/api/v1/agent-runs/{first.json()['run_id']}",
        headers={"Authorization": f"Bearer {_token(8)}"},
    )

    assert own.status_code == 200
    assert cross.status_code == 403
