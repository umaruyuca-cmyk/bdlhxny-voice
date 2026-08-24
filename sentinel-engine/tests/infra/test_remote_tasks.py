from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from bdlh_runtime.infra.remote_runtime_data import RuntimeDataClient
from bdlh_runtime.infra.remote_tasks import RemoteTaskStore
from bdlh_runtime.infra.tasks import (
    FinancialTask,
    FinancialTaskStatus,
    NotificationOutboxMessage,
    PriceConditionDirection,
    PriceThresholdCondition,
)

NOW = datetime(2026, 8, 16, tzinfo=UTC)


class Response:
    status_code = 200

    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._body


def task() -> FinancialTask:
    return FinancialTask(
        task_id="task-1",
        authenticated_user_id="7",
        status=FinancialTaskStatus.COMPLETED,
        condition=PriceThresholdCondition(symbol="600519", direction=PriceConditionDirection.AT_OR_ABOVE, threshold=10),
        confirmation_ref="confirmation-1",
        creation_fingerprint="a" * 64,
        cadence_seconds=300,
        next_wakeup_at=NOW,
        expires_at=NOW + timedelta(days=1),
        created_at=NOW,
        updated_at=NOW,
        version=3,
    )


def test_completion_is_one_java_use_case_call_with_stable_idempotency_key() -> None:
    calls: list[dict[str, Any]] = []

    def request(**kwargs: Any) -> Response:
        calls.append(kwargs)
        return Response({"eventId": "33333333-3333-3333-3333-333333333333", "status": "PENDING"})

    store = RemoteTaskStore(RuntimeDataClient(base_url="http://java-data", internal_token="token", request=request))
    item = task()
    message = NotificationOutboxMessage(
        outbox_id="33333333-3333-3333-3333-333333333333",
        task_id=item.task_id,
        authenticated_user_id=item.authenticated_user_id,
        idempotency_key="task-notification:task-1:2026-08-16T00:00:00+00:00",
        title="价格条件满足",
        body="通知内容",
        observed_price=11,
        currency="CNY",
        observation_time=NOW,
        created_at=NOW,
    )

    completed = store.complete_task_and_enqueue_notification(item, expected_version=3, notification=message)

    assert completed.version == 4
    assert len(calls) == 1
    assert calls[0]["path"] == "/internal/v1/tasks/task-1/complete-notification"
    assert calls[0]["params"] == {"user_id": 7}
    assert calls[0]["json"]["idempotencyKey"] == message.idempotency_key
    assert calls[0]["json"]["completedTaskPayload"]["status"] == "COMPLETED"
