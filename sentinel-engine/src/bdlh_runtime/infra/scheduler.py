"""M6 最小 Scheduler 与 Notification Outbox Worker。

Scheduler 只领取到期任务并投递 ``SCHEDULED_WAKEUP``；价格判断发生在唤醒
处理器中，最新数据只从本轮 ``market.get_realtime_quote`` Observation 读取。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from bdlh_runtime.engine.contracts import CognitiveExecution, InputEvent, InputEventType

from .tasks import (
    FinancialTask,
    FinancialTaskStatus,
    NotificationOutbox,
    NotificationOutboxMessage,
    PriceConditionDirection,
    TaskStore,
    new_outbox_id,
    utc_now,
)


class CognitiveWakeupPort(Protocol):
    async def run(self, event: InputEvent, *, observer: object | None = None) -> CognitiveExecution: ...


class NotificationSender(Protocol):
    async def send(self, message: NotificationOutboxMessage) -> None: ...


class NoopNotificationSender:
    """默认站内通知发送器；Outbox SENT 记录即为可查询的站内投递结果。"""

    async def send(self, message: NotificationOutboxMessage) -> None:
        del message


@dataclass(frozen=True)
class SchedulerTickResult:
    recovered: int = 0
    expired: int = 0
    claimed: int = 0
    waiting: int = 0
    triggered: int = 0
    failed: int = 0


class FinancialTaskWakeupHandler:
    def __init__(
        self,
        *,
        task_store: TaskStore,
        outbox: NotificationOutbox,
        cognitive: CognitiveWakeupPort,
    ) -> None:
        self._tasks = task_store
        self._outbox = outbox
        self._cognitive = cognitive

    async def handle(
        self,
        task: FinancialTask,
        *,
        wakeup_key: str,
        now: datetime | None = None,
    ) -> FinancialTask:
        timestamp = now or utc_now()
        expected_version = task.version
        if task.status != FinancialTaskStatus.RUNNING:
            raise ValueError("wakeup handler requires a RUNNING task")
        try:
            observer = _WakeupOutcomeObserver()
            await self._cognitive.run(
                InputEvent(
                    event_id=wakeup_key,
                    event_type=InputEventType.SCHEDULED_WAKEUP,
                    user_id=task.authenticated_user_id,
                    session_id=f"task:{task.task_id}",
                    run_id=f"task-wakeup:{wakeup_key}",
                    task_id=task.task_id,
                    task_domain="finance",
                    message=_wakeup_message(task),
                ),
                observer=observer,
            )
        except Exception as exc:
            task.last_limitation = f"WAKEUP_EXECUTION_FAILED:{type(exc).__name__}"
            task.transition(
                FinancialTaskStatus.WAITING,
                reason_code="WAKEUP_RETRYABLE_FAILURE",
                now=timestamp,
                wakeup_key=wakeup_key,
            )
            task.next_wakeup_at = timestamp + timedelta(seconds=task.cadence_seconds)
            return self._tasks.update(task, expected_version=expected_version)

        price, currency, observation_time, limitation = _fresh_price(observer.quote)
        if limitation is not None:
            task.last_limitation = limitation
            task.transition(
                FinancialTaskStatus.WAITING,
                reason_code="WAKEUP_DATA_LIMITED",
                now=timestamp,
                wakeup_key=wakeup_key,
            )
            task.next_wakeup_at = timestamp + timedelta(seconds=task.cadence_seconds)
            return self._tasks.update(task, expected_version=expected_version)

        assert price is not None and observation_time is not None
        if currency and currency.upper() != task.condition.currency.upper():
            task.last_limitation = "WAKEUP_CURRENCY_MISMATCH"
            task.transition(
                FinancialTaskStatus.WAITING,
                reason_code="WAKEUP_CURRENCY_MISMATCH",
                now=timestamp,
                wakeup_key=wakeup_key,
            )
            task.next_wakeup_at = timestamp + timedelta(seconds=task.cadence_seconds)
            return self._tasks.update(task, expected_version=expected_version)
        task.last_observed_price = price
        task.last_observation_time = observation_time
        task.last_limitation = None
        if not _condition_met(task, price):
            task.transition(
                FinancialTaskStatus.WAITING,
                reason_code="PRICE_CONDITION_NOT_MET",
                now=timestamp,
                wakeup_key=wakeup_key,
                details={"observed_price": price},
            )
            task.next_wakeup_at = timestamp + timedelta(seconds=task.cadence_seconds)
            return self._tasks.update(task, expected_version=expected_version)

        task.transition(
            FinancialTaskStatus.TRIGGERED,
            reason_code="PRICE_CONDITION_MET",
            now=timestamp,
            wakeup_key=wakeup_key,
            details={"observed_price": price},
        )
        notification_request = NotificationOutboxMessage(
            outbox_id=new_outbox_id(),
            task_id=task.task_id,
            authenticated_user_id=task.authenticated_user_id,
            idempotency_key=f"task-notification:{wakeup_key}",
            title=f"{task.condition.symbol} 价格观察条件已满足",
            body=_notification_body(task, price, currency or task.condition.currency),
            observed_price=price,
            currency=currency or task.condition.currency,
            observation_time=observation_time,
            created_at=timestamp,
        )
        task.notification_outbox_id = notification_request.outbox_id
        task.transition(
            FinancialTaskStatus.COMPLETED,
            reason_code="NOTIFICATION_ENQUEUED",
            now=timestamp,
            wakeup_key=wakeup_key,
            details={"outbox_id": notification_request.outbox_id},
        )
        complete_atomically = getattr(self._tasks, "complete_task_and_enqueue_notification", None)
        if callable(complete_atomically):
            return complete_atomically(task, expected_version=expected_version, notification=notification_request)
        notification = self._outbox.enqueue(notification_request)
        task.notification_outbox_id = notification.outbox_id
        return self._tasks.update(task, expected_version=expected_version)


class FinancialTaskScheduler:
    def __init__(
        self,
        *,
        task_store: TaskStore,
        wakeup_handler: FinancialTaskWakeupHandler,
        batch_size: int = 50,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._tasks = task_store
        self._handler = wakeup_handler
        self._batch_size = batch_size

    async def tick(self, *, now: datetime | None = None) -> SchedulerTickResult:
        timestamp = now or utc_now()
        recovered = self._tasks.recover_stale(
            now=timestamp,
            stale_before=timestamp - timedelta(minutes=5),
        )
        expired = self._tasks.expire_due(now=timestamp)
        claims = self._tasks.claim_due(now=timestamp, limit=self._batch_size)
        waiting = triggered = failed = 0
        for task, wakeup_key in claims:
            try:
                result = await self._handler.handle(task, wakeup_key=wakeup_key, now=timestamp)
                if result.status == FinancialTaskStatus.WAITING:
                    waiting += 1
                elif result.status == FinancialTaskStatus.COMPLETED:
                    triggered += 1
                elif result.status == FinancialTaskStatus.FAILED:
                    failed += 1
            except Exception:
                failed += 1
        return SchedulerTickResult(
            recovered=recovered,
            expired=expired,
            claimed=len(claims),
            waiting=waiting,
            triggered=triggered,
            failed=failed,
        )


class NotificationOutboxWorker:
    def __init__(
        self,
        *,
        outbox: NotificationOutbox,
        sender: NotificationSender | None = None,
        batch_size: int = 50,
    ) -> None:
        self._outbox = outbox
        self._sender = sender or NoopNotificationSender()
        self._batch_size = batch_size

    async def tick(self, *, now: datetime | None = None) -> int:
        timestamp = now or utc_now()
        sent = 0
        for message in self._outbox.claim_pending(limit=self._batch_size):
            try:
                await self._sender.send(message)
            except Exception as exc:
                self._outbox.mark_failed(message.outbox_id, error=type(exc).__name__)
                continue
            self._outbox.mark_sent(message.outbox_id, sent_at=timestamp)
            sent += 1
        return sent


async def run_worker_loop(
    *,
    scheduler: FinancialTaskScheduler,
    outbox_worker: NotificationOutboxWorker,
    poll_seconds: float,
    stop_event: asyncio.Event,
) -> None:
    """可由 ASGI lifespan 或独立 Worker 进程托管的轮询循环。"""

    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    while not stop_event.is_set():
        await scheduler.tick()
        await outbox_worker.tick()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
        except TimeoutError:
            continue


def _wakeup_message(task: FinancialTask) -> str:
    name = task.condition.instrument_name or task.condition.symbol
    return f"查询证券代码 {task.condition.symbol}（{name}）当前价格，用于已确认的价格观察任务。"


def _condition_met(task: FinancialTask, price: float) -> bool:
    if task.condition.direction == PriceConditionDirection.AT_OR_ABOVE:
        return price >= task.condition.threshold
    return price <= task.condition.threshold


@dataclass
class _WakeupOutcomeObserver:
    quote: Any = None

    def on_tool_observation(self, name: str, payload: Any) -> None:
        if name == "market.get_realtime_quote":
            self.quote = payload


def _as_mapping(payload: Any) -> dict[str, Any] | None:
    if payload is None:
        return None
    if hasattr(payload, "model_dump"):
        dumped = payload.model_dump(mode="python")
        return dumped if isinstance(dumped, dict) else None
    if isinstance(payload, dict):
        return payload
    return None


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _fresh_price(payload: Any) -> tuple[float | None, str | None, datetime | None, str | None]:
    """只接受本次唤醒留下的实时行情 Observation，不解析聊天文案。"""

    dumped = _as_mapping(payload)
    if dumped is None:
        return None, None, None, "WAKEUP_QUOTE_MISSING"
    status = dumped.get("status")
    if status in {"FAILED", "UNAVAILABLE", "PARTIAL", "LIMITED"}:
        return None, None, None, "WAKEUP_QUOTE_LIMITED"
    quality = dumped.get("data_quality")
    if isinstance(quality, dict) and quality.get("quality_status") in {"LOW", "INVALID", "STALE"}:
        return None, None, None, "WAKEUP_PRICE_QUALITY_LIMITED"
    data = dumped.get("data")
    if not isinstance(data, dict):
        data = dumped
    price = data.get("price") or data.get("last_price") or data.get("current_price")
    if not isinstance(price, (int, float)) or price <= 0:
        return None, None, None, "WAKEUP_PRICE_MISSING"
    source_time = (
        _parse_time(data.get("source_time"))
        or _parse_time(data.get("trade_date"))
        or _parse_time(data.get("retrieved_at"))
    )
    provenance = dumped.get("provenance")
    if source_time is None and isinstance(provenance, list) and provenance:
        first = provenance[0] if isinstance(provenance[0], dict) else _as_mapping(provenance[0])
        if isinstance(first, dict):
            source_time = _parse_time(first.get("retrieved_at") or first.get("as_of"))
    if source_time is None:
        return None, None, None, "WAKEUP_PRICE_TIME_MISSING"
    currency = str(data.get("currency") or dumped.get("currency") or "CNY")
    return float(price), currency, source_time, None


def _notification_body(task: FinancialTask, price: float, currency: str) -> str:
    comparison = "达到或高于" if task.condition.direction == PriceConditionDirection.AT_OR_ABOVE else "达到或低于"
    return (
        f"{task.condition.symbol} 最新可用价格为 {price:g} {currency}，"
        f"已{comparison}你确认的阈值 {task.condition.threshold:g} {task.condition.currency}。"
        "该通知仅报告观察条件，不构成交易建议。"
    )
