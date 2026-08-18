from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from bdlh_runtime.api.routes import create_api_app
from bdlh_runtime.config import Settings
from bdlh_runtime.runtime.application import create_application
from tests.helpers_registry import seeded_snapshot


SECRET = "test-jwt-secret-with-at-least-thirty-two-bytes"


def _token(user_id: int, *, expired: bool = False) -> str:
    now = datetime.now(timezone.utc)
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
    application = create_application(
        Settings(environment="development", auth_required=True, jwt_secret=SECRET),
        registry_snapshot=seeded_snapshot(),
    )
    return application, TestClient(create_api_app(application))


def test_agent_runs_require_a_valid_java_issued_jwt():
    _, client = _client()

    missing = client.post("/api/v1/agent-runs", json={"message": "什么是市盈率？"})
    expired = client.post(
        "/api/v1/agent-runs",
        headers={"Authorization": f"Bearer {_token(7, expired=True)}"},
        json={"message": "什么是市盈率？"},
    )

    assert missing.status_code == 401
    assert expired.status_code == 401


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
    assert first_location.thread_id == f"user:7:thread:{common_thread}"
    assert second_location.thread_id == f"user:8:thread:{common_thread}"

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
