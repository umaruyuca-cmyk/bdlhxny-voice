from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient

from bdlh_runtime.api.routes import create_api_app
from bdlh_runtime.config import Settings
from bdlh_runtime.runtime.application import create_application
from tests.helpers_registry import seeded_snapshot

SECRET = "m6-test-jwt-secret-with-at-least-thirty-two-bytes"


def headers(user: int) -> dict[str, str]:
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(user), "iat": now, "exp": now + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_financial_task_crud_is_authenticated_and_user_scoped() -> None:
    application = create_application(
        Settings(
            environment="test",
            auth_required=True,
            jwt_secret=SECRET,
        ),
        registry_snapshot=seeded_snapshot(),
    )
    client = TestClient(create_api_app(application))
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    payload = {
        "symbol": "600519",
        "direction": "AT_OR_ABOVE",
        "threshold": 1500,
        "expires_at": expires_at.isoformat(),
        "confirmed": True,
    }

    assert client.post("/api/v1/financial-tasks", json=payload).status_code == 401
    created = client.post(
        "/api/v1/financial-tasks",
        json=payload,
        headers={**headers(1), "Idempotency-Key": "create-task-1"},
    )
    assert created.status_code == 201
    task_id = created.json()["task_id"]
    assert created.json()["status"] == "SCHEDULED"
    assert created.json()["authenticated_user_id"] == "1"
    repeated = client.post(
        "/api/v1/financial-tasks",
        json=payload,
        headers={**headers(1), "Idempotency-Key": "create-task-1"},
    )
    assert repeated.status_code == 201
    assert repeated.json()["task_id"] == task_id
    conflict_payload = {**payload, "threshold": 1400}
    conflict = client.post(
        "/api/v1/financial-tasks",
        json=conflict_payload,
        headers={**headers(1), "Idempotency-Key": "create-task-1"},
    )
    assert conflict.status_code == 409

    assert client.get(f"/api/v1/financial-tasks/{task_id}", headers=headers(2)).status_code == 404
    listing = client.get("/api/v1/financial-tasks", headers=headers(1))
    assert [item["task_id"] for item in listing.json()] == [task_id]

    cancelled = client.post(f"/api/v1/financial-tasks/{task_id}/cancel", headers=headers(1))
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["audit_events"][-1]["reason_code"] == "USER_CANCELLED_TASK"


def test_cancel_version_conflict_while_running_returns_409() -> None:
    application = create_application(
        Settings(
            environment="test",
            auth_required=True,
            jwt_secret=SECRET,
        ),
        registry_snapshot=seeded_snapshot(),
    )
    client = TestClient(create_api_app(application))
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    created = client.post(
        "/api/v1/financial-tasks",
        json={
            "symbol": "600519",
            "direction": "AT_OR_ABOVE",
            "threshold": 1500,
            "expires_at": expires_at.isoformat(),
            "confirmed": True,
        },
        headers={**headers(1), "Idempotency-Key": "cancel-race-1"},
    )
    assert created.status_code == 201
    task_id = created.json()["task_id"]
    claimed = application.task_store.claim_due(
        now=datetime.now(UTC) + timedelta(seconds=1),
        limit=1,
    )
    assert len(claimed) == 1
    assert claimed[0][0].task_id == task_id

    conflict = client.post(f"/api/v1/financial-tasks/{task_id}/cancel", headers=headers(1))
    assert conflict.status_code == 409
    assert "正在执行" in conflict.json()["detail"]
