"""Java Data Plane adapters for the P3 Task/Outbox cutover."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .remote_runtime_data import RuntimeDataClient
from .tasks import FinancialTask, NotificationOutboxMessage, utc_now


class RemoteTaskStore:
    """Task state is Java-owned; Python retains only scheduler and domain orchestration."""

    def __init__(self, client: RuntimeDataClient) -> None:
        self._client = client

    def create(self, task: FinancialTask) -> FinancialTask:
        return _task(
            self._client.call("POST", "/internal/v1/tasks", task.authenticated_user_id, payload=_save_payload(task))
        )

    def update(self, task: FinancialTask, *, expected_version: int) -> FinancialTask:
        return _task(
            self._client.call(
                "PUT",
                f"/internal/v1/tasks/{task.task_id}",
                task.authenticated_user_id,
                payload=_save_payload(task, expected_version=expected_version),
            )
        )

    def get(self, task_id: str, authenticated_user_id: str) -> FinancialTask | None:
        data = self._client.call("GET", f"/internal/v1/tasks/{task_id}", authenticated_user_id, allow_not_found=True)
        return _task(data) if data is not None else None

    def list_for_user(self, authenticated_user_id: str, *, limit: int = 100) -> list[FinancialTask]:
        data = self._client.call("GET", "/internal/v1/tasks", authenticated_user_id, query={"limit": max(1, limit)})
        if not isinstance(data, list):
            raise RuntimeError("Java Task API returned an invalid task list")
        return [_task(item) for item in data]

    def claim_due(self, *, now: datetime, limit: int) -> list[tuple[FinancialTask, str]]:
        del now  # Database time is authoritative for a cross-process claim.
        data = self._client.call_internal(
            "POST", "/internal/v1/task-scheduler/claim-due", query={"limit": max(1, limit)}
        )
        if not isinstance(data, list):
            raise RuntimeError("Java Task API returned an invalid claim result")
        tasks = [_task(item) for item in data]
        return [(task, f"{task.task_id}:{task.next_wakeup_at.isoformat()}") for task in tasks]

    def expire_due(self, *, now: datetime) -> int:
        del now
        data = self._client.call_internal("POST", "/internal/v1/task-scheduler/expire-due")
        return int(data)

    def recover_stale(self, *, now: datetime, stale_before: datetime) -> int:
        del now, stale_before
        data = self._client.call_internal("POST", "/internal/v1/task-scheduler/recover-stale")
        return int(data)

    def complete_task_and_enqueue_notification(
        self,
        task: FinancialTask,
        *,
        expected_version: int,
        notification: NotificationOutboxMessage,
    ) -> FinancialTask:
        self._client.call(
            "POST",
            f"/internal/v1/tasks/{task.task_id}/complete-notification",
            task.authenticated_user_id,
            payload={
                "expectedVersion": expected_version,
                "eventId": notification.outbox_id,
                "idempotencyKey": notification.idempotency_key,
                "notificationPayload": notification.model_dump(mode="json"),
                "completedTaskPayload": task.model_dump(mode="json"),
                "traceId": f"task:{task.task_id}",
                "correlationId": notification.idempotency_key,
            },
        )
        task.version = expected_version + 1
        task.updated_at = utc_now()
        return task


class RemoteNotificationOutbox:
    """P3 deliberately has no Python publisher; Java Relay is introduced in P4."""

    def __init__(self, client: RuntimeDataClient) -> None:
        self._client = client

    def enqueue(self, message: NotificationOutboxMessage) -> NotificationOutboxMessage:
        raise RuntimeError("Java Task Store must complete task and enqueue notification atomically")

    def claim_pending(self, *, limit: int) -> list[NotificationOutboxMessage]:
        del limit
        return []

    def mark_sent(self, outbox_id: str, *, sent_at: datetime) -> NotificationOutboxMessage:
        del outbox_id, sent_at
        raise RuntimeError("notification delivery is owned by the Java Relay")

    def mark_failed(self, outbox_id: str, *, error: str) -> NotificationOutboxMessage:
        del outbox_id, error
        raise RuntimeError("notification delivery is owned by the Java Relay")

    def list_for_user(self, authenticated_user_id: str, *, limit: int = 100) -> list[NotificationOutboxMessage]:
        data = self._client.call(
            "GET",
            "/internal/v1/notifications",
            authenticated_user_id,
            query={"limit": max(1, limit)},
        )
        if not isinstance(data, list):
            raise RuntimeError("Java Notification API returned an invalid notification list")
        return [
            NotificationOutboxMessage(
                outbox_id=str(item["notificationId"]),
                task_id=str(item["taskId"]),
                authenticated_user_id=authenticated_user_id,
                idempotency_key=f"event:{item['notificationId']}",
                channel=str(item.get("channel") or "IN_APP"),
                status="SENT",
                title=str(item["title"]),
                body=str(item["body"]),
                observed_price=float(item["observedPrice"]),
                currency=str(item.get("currency") or "CNY"),
                observation_time=item["observationTime"],
                created_at=item["createdAt"],
                sent_at=item["createdAt"],
            )
            for item in data
        ]


def create_remote_task_stores(
    *, base_url: str | None, internal_token: str | None
) -> tuple[RemoteTaskStore, RemoteNotificationOutbox]:
    if not base_url:
        raise RuntimeError("远程 Task Store 需要 JAVA_API_BASE_URL")
    if not internal_token:
        raise RuntimeError("Java task scheduler requires JAVA_DATA_INTERNAL_TOKEN")
    client = RuntimeDataClient(base_url=base_url, internal_token=internal_token)
    return RemoteTaskStore(client), RemoteNotificationOutbox(client)


def _save_payload(task: FinancialTask, *, expected_version: int | None = None) -> dict[str, Any]:
    return {
        "taskId": task.task_id,
        "status": task.status.value,
        "version": task.version,
        "expectedVersion": expected_version,
        "nextWakeupAt": task.next_wakeup_at,
        "expiresAt": task.expires_at,
        "payload": task.model_dump(mode="json"),
    }


def _task(data: dict[str, Any] | None) -> FinancialTask:
    if not isinstance(data, dict) or not isinstance(data.get("payload"), dict):
        raise RuntimeError("Java Task API returned an invalid task snapshot")
    payload = dict(data["payload"])
    payload.update(
        {
            "task_id": data["taskId"],
            "status": data["status"],
            "version": data["version"],
            "next_wakeup_at": data["nextWakeupAt"],
            "expires_at": data["expiresAt"],
        }
    )
    return FinancialTask.model_validate(payload)
