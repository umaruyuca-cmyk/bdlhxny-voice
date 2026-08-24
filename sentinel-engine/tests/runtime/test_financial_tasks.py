from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from bdlh_runtime.cognitive.contracts import (
    CognitiveState,
    InputEvent,
    InputEventType,
    PublicResponse,
)
from bdlh_runtime.cognitive.orchestrator import CognitiveExecution
from bdlh_runtime.domains.contracts import ConfidenceAssessment
from bdlh_runtime.domains.finance.contracts import (
    FinancialDomainOutcome,
    FinancialInstrument,
    MarketSnapshot,
    StockResearchResult,
)
from bdlh_runtime.runtime.scheduler import (
    FinancialTaskScheduler,
    FinancialTaskWakeupHandler,
    NotificationOutboxWorker,
)
from bdlh_runtime.runtime.tasks import (
    FinancialTask,
    FinancialTaskStatus,
    InMemoryNotificationOutbox,
    InMemoryTaskStore,
    PriceConditionDirection,
    PriceThresholdCondition,
    TaskAuditEvent,
)

NOW = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)


def task(*, threshold: float = 10, expires_at: datetime | None = None) -> FinancialTask:
    return FinancialTask(
        task_id="task-1",
        authenticated_user_id="user-1",
        status=FinancialTaskStatus.SCHEDULED,
        condition=PriceThresholdCondition(
            symbol="600519",
            direction=PriceConditionDirection.AT_OR_ABOVE,
            threshold=threshold,
        ),
        confirmation_ref="confirmation-1",
        creation_fingerprint="a" * 64,
        cadence_seconds=300,
        next_wakeup_at=NOW,
        expires_at=expires_at or NOW + timedelta(days=1),
        created_at=NOW - timedelta(minutes=1),
        updated_at=NOW - timedelta(minutes=1),
        audit_events=[
            TaskAuditEvent(
                event_type="task.scheduled",
                occurred_at=NOW - timedelta(minutes=1),
                reason_code="USER_CONFIRMED_PRICE_OBSERVATION",
            )
        ],
    )


class FinanceWakeup:
    def __init__(self, *, price: float | None, status: str = "COMPLETE") -> None:
        self.price = price
        self.status = status
        self.events: list[InputEvent] = []

    async def run(self, event: InputEvent, *, observer: Any = None, checkpoint: Any = None) -> CognitiveExecution:
        del checkpoint
        self.events.append(event)
        research = StockResearchResult(
            instrument=FinancialInstrument(symbol="600519"),
            market_snapshot=MarketSnapshot(
                symbol="600519",
                price=self.price,
                currency="CNY",
                source_time=NOW,
                quality="HIGH" if self.price else "LOW",
            )
            if self.price
            else None,
            coverage="COMPLETE" if self.price else "LIMITED",
            confidence=ConfidenceAssessment(
                level="HIGH" if self.price else "LOW",
                coverage_status="COMPLETE" if self.price else "LIMITED",
            ),
        )
        outcome = FinancialDomainOutcome(
            request_id=f"{event.event_id}:research",
            status=self.status,  # type: ignore[arg-type]
            stock_research_result=research,
            confidence=research.confidence,
            limitations=[] if self.price else ["price unavailable"],
        )
        observer.on_domain_outcome(outcome)
        return CognitiveExecution(
            state=CognitiveState(event=event),
            response=PublicResponse(
                response_kind="DOMAIN_RESULT" if self.price else "LIMITED",
                response_structure="RESEARCH",
                message="done",
            ),
        )


def scheduler(cognitive: FinanceWakeup):
    store = InMemoryTaskStore()
    outbox = InMemoryNotificationOutbox()
    store.create(task())
    handler = FinancialTaskWakeupHandler(
        task_store=store,
        outbox=outbox,
        cognitive=cognitive,
    )
    return store, outbox, FinancialTaskScheduler(task_store=store, wakeup_handler=handler)


def test_scheduled_wakeup_requires_task_id() -> None:
    with pytest.raises(ValidationError, match="SCHEDULED_WAKEUP requires task_id"):
        InputEvent(
            event_id="event",
            event_type=InputEventType.SCHEDULED_WAKEUP,
            user_id="user-1",
            session_id="session",
            message="wake",
        )


def test_scheduled_wakeup_requires_task_domain() -> None:
    with pytest.raises(ValidationError, match="SCHEDULED_WAKEUP requires task_domain"):
        InputEvent(
            event_id="event",
            event_type=InputEventType.SCHEDULED_WAKEUP,
            user_id="user-1",
            session_id="session",
            message="wake",
            task_id="task-1",
        )


def test_invalid_state_transition_is_rejected() -> None:
    item = task()
    with pytest.raises(ValueError, match="invalid task transition"):
        item.transition(
            FinancialTaskStatus.COMPLETED,
            reason_code="INVALID",
            now=NOW,
        )


@pytest.mark.asyncio
async def test_scheduler_refreshes_finance_and_waits_when_condition_not_met() -> None:
    cognitive = FinanceWakeup(price=9)
    store, outbox, worker = scheduler(cognitive)

    result = await worker.tick(now=NOW)

    persisted = store.get("task-1", "user-1")
    assert result.claimed == 1
    assert result.waiting == 1
    assert persisted is not None and persisted.status == FinancialTaskStatus.WAITING
    assert persisted.last_observed_price == 9
    assert persisted.next_wakeup_at == NOW + timedelta(seconds=300)
    assert cognitive.events[0].event_type == InputEventType.SCHEDULED_WAKEUP
    assert cognitive.events[0].task_domain == "finance"
    assert outbox.list_for_user("user-1") == []


@pytest.mark.asyncio
async def test_limited_data_never_triggers_notification() -> None:
    cognitive = FinanceWakeup(price=None, status="LIMITED")
    store, outbox, worker = scheduler(cognitive)

    result = await worker.tick(now=NOW)

    persisted = store.get("task-1", "user-1")
    assert result.waiting == 1
    assert persisted is not None
    assert persisted.status == FinancialTaskStatus.WAITING
    assert persisted.last_limitation == "WAKEUP_FINANCE_DATA_LIMITED"
    assert outbox.claim_pending(limit=10) == []


@pytest.mark.asyncio
async def test_trigger_enqueues_and_sends_exactly_one_notification() -> None:
    cognitive = FinanceWakeup(price=11)
    store, outbox, worker = scheduler(cognitive)

    first = await worker.tick(now=NOW)
    duplicate = await worker.tick(now=NOW)
    sender = NotificationOutboxWorker(outbox=outbox)
    assert await sender.tick(now=NOW) == 1
    assert await sender.tick(now=NOW) == 0

    persisted = store.get("task-1", "user-1")
    notifications = outbox.list_for_user("user-1")
    assert first.triggered == 1
    assert duplicate.claimed == 0
    assert persisted is not None and persisted.status == FinancialTaskStatus.COMPLETED
    assert len(notifications) == 1
    assert notifications[0].observed_price == 11


@pytest.mark.asyncio
async def test_expired_task_is_not_woken() -> None:
    store = InMemoryTaskStore()
    outbox = InMemoryNotificationOutbox()
    expired_task = task(expires_at=NOW)
    # 模型要求创建后才算过期；等于 tick 时间仍视为有效并应过期。
    store.create(expired_task)
    cognitive = FinanceWakeup(price=11)
    worker = FinancialTaskScheduler(
        task_store=store,
        wakeup_handler=FinancialTaskWakeupHandler(task_store=store, outbox=outbox, cognitive=cognitive),
    )

    result = await worker.tick(now=NOW)

    persisted = store.get("task-1", "user-1")
    assert result.expired == 1 and result.claimed == 0
    assert persisted is not None and persisted.status == FinancialTaskStatus.EXPIRED
    assert cognitive.events == []


@pytest.mark.asyncio
async def test_stale_running_wakeup_is_recovered_with_the_same_idempotency_slot() -> None:
    cognitive = FinanceWakeup(price=11)
    store, outbox, worker = scheduler(cognitive)
    claims = store.claim_due(now=NOW, limit=1)
    assert len(claims) == 1
    stale = store.get("task-1", "user-1")
    assert stale is not None
    stale.updated_at = NOW - timedelta(minutes=10)
    store._tasks[stale.task_id] = stale  # injected crash after claim, before handler

    result = await worker.tick(now=NOW)

    persisted = store.get("task-1", "user-1")
    assert result.recovered == 1
    assert result.claimed == 1
    assert result.triggered == 1
    assert persisted is not None and persisted.status == FinancialTaskStatus.COMPLETED
    assert len(outbox.claim_pending(limit=10)) == 1


def test_store_is_user_isolated_and_cancel_audit_is_persisted() -> None:
    store = InMemoryTaskStore()
    created = store.create(task())
    assert store.get(created.task_id, "other-user") is None
    expected = created.version
    created.transition(
        FinancialTaskStatus.CANCELLED,
        reason_code="USER_CANCELLED_TASK",
        now=NOW,
    )
    cancelled = store.update(created, expected_version=expected)
    assert cancelled.status == FinancialTaskStatus.CANCELLED
    assert cancelled.audit_events[-1].reason_code == "USER_CANCELLED_TASK"


class FlakySender:
    def __init__(self) -> None:
        self.calls = 0

    async def send(self, message: Any) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient")


@pytest.mark.asyncio
async def test_failed_notification_is_retried_without_duplicate_outbox_rows() -> None:
    cognitive = FinanceWakeup(price=11)
    _, outbox, worker = scheduler(cognitive)
    await worker.tick(now=NOW)
    sender = FlakySender()
    outbox_worker = NotificationOutboxWorker(outbox=outbox, sender=sender)

    assert await outbox_worker.tick(now=NOW) == 0
    assert await outbox_worker.tick(now=NOW + timedelta(seconds=1)) == 1
    assert len(outbox.list_for_user("user-1")) == 1
    assert sender.calls == 2
