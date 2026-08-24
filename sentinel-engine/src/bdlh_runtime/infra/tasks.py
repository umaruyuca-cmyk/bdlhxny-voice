"""M6 金融持续任务契约、状态机与持久化边界。

首个且唯一启用的任务类型是价格阈值观察。任务只保存用户确认的观察条件，
不保存或复用历史研究结论；每次唤醒必须由 Scheduler 重新进入 Cognitive 与
Finance Runtime 获取最新数据。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bdlh_runtime.infra.errors import ConfigurationError


def utc_now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


class FinancialTaskStatus(StrEnum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    TRIGGERED = "TRIGGERED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class PriceConditionDirection(StrEnum):
    AT_OR_ABOVE = "AT_OR_ABOVE"
    AT_OR_BELOW = "AT_OR_BELOW"


class NotificationStatus(StrEnum):
    PENDING = "PENDING"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED = "FAILED"


TERMINAL_TASK_STATUSES = frozenset(
    {
        FinancialTaskStatus.COMPLETED,
        FinancialTaskStatus.FAILED,
        FinancialTaskStatus.CANCELLED,
        FinancialTaskStatus.EXPIRED,
    }
)

_TRANSITIONS: dict[FinancialTaskStatus, frozenset[FinancialTaskStatus]] = {
    FinancialTaskStatus.DRAFT: frozenset({FinancialTaskStatus.SCHEDULED, FinancialTaskStatus.CANCELLED}),
    FinancialTaskStatus.SCHEDULED: frozenset(
        {FinancialTaskStatus.RUNNING, FinancialTaskStatus.CANCELLED, FinancialTaskStatus.EXPIRED}
    ),
    FinancialTaskStatus.WAITING: frozenset(
        {FinancialTaskStatus.RUNNING, FinancialTaskStatus.CANCELLED, FinancialTaskStatus.EXPIRED}
    ),
    FinancialTaskStatus.RUNNING: frozenset(
        {
            FinancialTaskStatus.WAITING,
            FinancialTaskStatus.TRIGGERED,
            FinancialTaskStatus.FAILED,
            FinancialTaskStatus.CANCELLED,
            FinancialTaskStatus.EXPIRED,
        }
    ),
    FinancialTaskStatus.TRIGGERED: frozenset({FinancialTaskStatus.COMPLETED, FinancialTaskStatus.FAILED}),
    FinancialTaskStatus.COMPLETED: frozenset(),
    FinancialTaskStatus.FAILED: frozenset(),
    FinancialTaskStatus.CANCELLED: frozenset(),
    FinancialTaskStatus.EXPIRED: frozenset(),
}


class TaskAuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: str = Field(min_length=1)
    occurred_at: datetime
    reason_code: str = Field(min_length=1)
    wakeup_key: str | None = None
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_time(self) -> TaskAuditEvent:
        _aware(self.occurred_at, "occurred_at")
        return self


class PriceThresholdCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(pattern=r"^\d{6}$")
    market: Literal["CN"] = "CN"
    instrument_name: str | None = Field(default=None, max_length=128)
    direction: PriceConditionDirection
    threshold: float = Field(gt=0, allow_inf_nan=False)
    currency: Literal["CNY"] = "CNY"

    @model_validator(mode="after")
    def normalize_identity(self) -> PriceThresholdCondition:
        if not self.symbol.strip():
            raise ValueError("symbol must not be blank")
        return self


class FinancialTask(BaseModel):
    """价格观察任务的持久化真源；状态变更只能经显式状态机。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    authenticated_user_id: str = Field(min_length=1)
    task_type: str = Field(default="PRICE_THRESHOLD", pattern="^PRICE_THRESHOLD$")
    status: FinancialTaskStatus = FinancialTaskStatus.DRAFT
    condition: PriceThresholdCondition
    confirmation_ref: str = Field(min_length=1)
    creation_fingerprint: str = Field(min_length=64, max_length=64)
    cadence_seconds: int = Field(ge=60, le=86_400)
    next_wakeup_at: datetime
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
    last_wakeup_at: datetime | None = None
    last_observed_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    last_observation_time: datetime | None = None
    last_limitation: str | None = None
    notification_outbox_id: str | None = None
    version: int = Field(default=0, ge=0)
    audit_events: list[TaskAuditEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_task(self) -> FinancialTask:
        for name in ("next_wakeup_at", "expires_at", "created_at", "updated_at"):
            _aware(getattr(self, name), name)
        for name in ("last_wakeup_at", "last_observation_time"):
            value = getattr(self, name)
            if value is not None:
                _aware(value, name)
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        if not self.authenticated_user_id.strip():
            raise ValueError("authenticated_user_id must come from authentication")
        if not self.confirmation_ref.strip():
            raise ValueError("confirmation_ref is required before scheduling")
        return self

    def transition(
        self,
        target: FinancialTaskStatus,
        *,
        reason_code: str,
        now: datetime | None = None,
        wakeup_key: str | None = None,
        details: dict[str, str | int | float | bool | None] | None = None,
    ) -> None:
        if target not in _TRANSITIONS[self.status]:
            raise ValueError(f"invalid task transition: {self.status} -> {target}")
        timestamp = _aware(now or utc_now(), "transition time")
        self.status = target
        self.updated_at = timestamp
        self.audit_events.append(
            TaskAuditEvent(
                event_type=f"task.{target.value.lower()}",
                occurred_at=timestamp,
                reason_code=reason_code,
                wakeup_key=wakeup_key,
                details=details or {},
            )
        )


class NotificationOutboxMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outbox_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    authenticated_user_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    channel: str = Field(default="IN_APP", pattern="^IN_APP$")
    status: NotificationStatus = NotificationStatus.PENDING
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=2_000)
    observed_price: float = Field(gt=0, allow_inf_nan=False)
    currency: str = Field(min_length=3, max_length=8)
    observation_time: datetime
    created_at: datetime
    sent_at: datetime | None = None
    attempts: int = Field(default=0, ge=0)
    last_error: str | None = None

    @model_validator(mode="after")
    def validate_times(self) -> NotificationOutboxMessage:
        _aware(self.observation_time, "observation_time")
        _aware(self.created_at, "created_at")
        if self.sent_at is not None:
            _aware(self.sent_at, "sent_at")
        return self


class TaskStore(Protocol):
    def create(self, task: FinancialTask) -> FinancialTask: ...
    def update(self, task: FinancialTask, *, expected_version: int) -> FinancialTask: ...
    def get(self, task_id: str, authenticated_user_id: str) -> FinancialTask | None: ...
    def list_for_user(self, authenticated_user_id: str, *, limit: int = 100) -> list[FinancialTask]: ...
    def claim_due(self, *, now: datetime, limit: int) -> list[tuple[FinancialTask, str]]: ...
    def expire_due(self, *, now: datetime) -> int: ...
    def recover_stale(self, *, now: datetime, stale_before: datetime) -> int: ...


class NotificationOutbox(Protocol):
    def enqueue(self, message: NotificationOutboxMessage) -> NotificationOutboxMessage: ...
    def claim_pending(self, *, limit: int) -> list[NotificationOutboxMessage]: ...
    def mark_sent(self, outbox_id: str, *, sent_at: datetime) -> NotificationOutboxMessage: ...
    def mark_failed(self, outbox_id: str, *, error: str) -> NotificationOutboxMessage: ...
    def list_for_user(self, authenticated_user_id: str, *, limit: int = 100) -> list[NotificationOutboxMessage]: ...


def _copy_task(task: FinancialTask) -> FinancialTask:
    return task.model_copy(deep=True)


def _copy_message(message: NotificationOutboxMessage) -> NotificationOutboxMessage:
    return message.model_copy(deep=True)


class InMemoryTaskStore:
    """开发/测试实现；锁内 claim 保证同一唤醒只被一个 Worker 获取。"""

    def __init__(self) -> None:
        self._tasks: dict[str, FinancialTask] = {}
        self._claimed_wakeups: set[str] = set()
        self._lock = RLock()

    def create(self, task: FinancialTask) -> FinancialTask:
        with self._lock:
            if task.task_id in self._tasks:
                return _copy_task(self._tasks[task.task_id])
            self._tasks[task.task_id] = _copy_task(task)
            return _copy_task(task)

    def update(self, task: FinancialTask, *, expected_version: int) -> FinancialTask:
        with self._lock:
            current = self._tasks.get(task.task_id)
            if current is None:
                raise KeyError(f"task not found: {task.task_id}")
            if current.version != expected_version:
                raise RuntimeError("TASK_VERSION_CONFLICT")
            updated = _copy_task(task)
            updated.version = expected_version + 1
            self._tasks[task.task_id] = updated
            return _copy_task(updated)

    def get(self, task_id: str, authenticated_user_id: str) -> FinancialTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.authenticated_user_id != authenticated_user_id:
                return None
            return _copy_task(task)

    def list_for_user(self, authenticated_user_id: str, *, limit: int = 100) -> list[FinancialTask]:
        with self._lock:
            tasks = [
                _copy_task(task) for task in self._tasks.values() if task.authenticated_user_id == authenticated_user_id
            ]
        return sorted(tasks, key=lambda item: item.updated_at, reverse=True)[: max(1, limit)]

    def claim_due(self, *, now: datetime, limit: int) -> list[tuple[FinancialTask, str]]:
        timestamp = _aware(now, "now")
        claimed: list[tuple[FinancialTask, str]] = []
        with self._lock:
            due = sorted(
                (
                    task
                    for task in self._tasks.values()
                    if task.status in {FinancialTaskStatus.SCHEDULED, FinancialTaskStatus.WAITING}
                    and task.next_wakeup_at <= timestamp < task.expires_at
                ),
                key=lambda item: item.next_wakeup_at,
            )
            for current in due[: max(1, limit)]:
                scheduled_for = current.next_wakeup_at.astimezone(UTC).isoformat()
                wakeup_key = f"{current.task_id}:{scheduled_for}"
                if wakeup_key in self._claimed_wakeups:
                    continue
                self._claimed_wakeups.add(wakeup_key)
                expected = current.version
                task = _copy_task(current)
                task.last_wakeup_at = timestamp
                task.transition(
                    FinancialTaskStatus.RUNNING,
                    reason_code="SCHEDULED_WAKEUP_CLAIMED",
                    now=timestamp,
                    wakeup_key=wakeup_key,
                )
                task.version = expected + 1
                self._tasks[task.task_id] = _copy_task(task)
                claimed.append((_copy_task(task), wakeup_key))
        return claimed

    def expire_due(self, *, now: datetime) -> int:
        timestamp = _aware(now, "now")
        expired = 0
        with self._lock:
            for current in list(self._tasks.values()):
                if (
                    current.status in {FinancialTaskStatus.SCHEDULED, FinancialTaskStatus.WAITING}
                    and current.expires_at <= timestamp
                ):
                    task = _copy_task(current)
                    task.transition(
                        FinancialTaskStatus.EXPIRED,
                        reason_code="TASK_EXPIRY_REACHED",
                        now=timestamp,
                    )
                    task.version = current.version + 1
                    self._tasks[task.task_id] = task
                    expired += 1
        return expired

    def recover_stale(self, *, now: datetime, stale_before: datetime) -> int:
        timestamp = _aware(now, "now")
        cutoff = _aware(stale_before, "stale_before")
        recovered = 0
        with self._lock:
            for current in list(self._tasks.values()):
                if current.status == FinancialTaskStatus.RUNNING and current.updated_at <= cutoff:
                    task = _copy_task(current)
                    wakeup_key = f"{task.task_id}:{task.next_wakeup_at.astimezone(UTC).isoformat()}"
                    self._claimed_wakeups.discard(wakeup_key)
                    task.transition(
                        FinancialTaskStatus.WAITING,
                        reason_code="STALE_WAKEUP_RECOVERED",
                        now=timestamp,
                    )
                    task.version = current.version + 1
                    self._tasks[task.task_id] = task
                    recovered += 1
        return recovered


class InMemoryNotificationOutbox:
    def __init__(self) -> None:
        self._messages: dict[str, NotificationOutboxMessage] = {}
        self._idempotency: dict[str, str] = {}
        self._lock = RLock()

    def enqueue(self, message: NotificationOutboxMessage) -> NotificationOutboxMessage:
        with self._lock:
            existing_id = self._idempotency.get(message.idempotency_key)
            if existing_id is not None:
                return _copy_message(self._messages[existing_id])
            self._messages[message.outbox_id] = _copy_message(message)
            self._idempotency[message.idempotency_key] = message.outbox_id
            return _copy_message(message)

    def claim_pending(self, *, limit: int) -> list[NotificationOutboxMessage]:
        claimed: list[NotificationOutboxMessage] = []
        with self._lock:
            for current in sorted(self._messages.values(), key=lambda item: item.created_at):
                if current.status not in {NotificationStatus.PENDING, NotificationStatus.FAILED}:
                    continue
                if current.attempts >= 3:
                    continue
                message = _copy_message(current)
                message.status = NotificationStatus.SENDING
                message.attempts += 1
                self._messages[message.outbox_id] = _copy_message(message)
                claimed.append(message)
                if len(claimed) >= max(1, limit):
                    break
        return claimed

    def mark_sent(self, outbox_id: str, *, sent_at: datetime) -> NotificationOutboxMessage:
        with self._lock:
            message = _copy_message(self._messages[outbox_id])
            if message.status == NotificationStatus.SENT:
                return message
            message.status = NotificationStatus.SENT
            message.sent_at = _aware(sent_at, "sent_at")
            message.last_error = None
            self._messages[outbox_id] = _copy_message(message)
            return message

    def mark_failed(self, outbox_id: str, *, error: str) -> NotificationOutboxMessage:
        with self._lock:
            message = _copy_message(self._messages[outbox_id])
            message.status = NotificationStatus.FAILED
            message.last_error = str(error)[:500]
            self._messages[outbox_id] = _copy_message(message)
            return message

    def list_for_user(self, authenticated_user_id: str, *, limit: int = 100) -> list[NotificationOutboxMessage]:
        with self._lock:
            messages = [
                _copy_message(message)
                for message in self._messages.values()
                if message.authenticated_user_id == authenticated_user_id and message.status == NotificationStatus.SENT
            ]
        return sorted(messages, key=lambda item: item.sent_at or item.created_at, reverse=True)[: max(1, limit)]


class PostgresTaskStore:
    """生产 Task Store；表结构由显式 migration 创建。"""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._validate_dependency()
        self._validate_schema("bdlh_runtime_financial_task")

    @staticmethod
    def _validate_dependency() -> None:
        try:
            import psycopg  # noqa: F401
        except ImportError as exc:
            raise ConfigurationError("PostgreSQL Task Store 需要 psycopg[binary]") from exc

    def _connect(self):
        import psycopg

        return psycopg.connect(self._dsn)

    def _validate_schema(self, table_name: str) -> None:
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT to_regclass(%s)", (f"public.{table_name}",)).fetchone()
        except Exception as exc:
            raise ConfigurationError(f"PostgreSQL M6 Store 初始化失败: {exc}") from exc
        if row is None or row[0] is None:
            raise ConfigurationError("缺少 M6 PostgreSQL migration: 20260812_financial_tasks.sql")

    @staticmethod
    def _decode(payload: object) -> FinancialTask:
        if isinstance(payload, str):
            payload = json.loads(payload)
        return FinancialTask.model_validate(payload)

    @staticmethod
    def _payload(task: FinancialTask) -> str:
        return task.model_dump_json()

    def create(self, task: FinancialTask) -> FinancialTask:
        with self._connect() as connection:
            row = connection.execute(
                """
                INSERT INTO bdlh_runtime_financial_task(
                    task_id, user_id, status, next_wakeup_at, expires_at, version, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (task_id) DO NOTHING
                RETURNING payload
                """,
                (
                    task.task_id,
                    task.authenticated_user_id,
                    task.status.value,
                    task.next_wakeup_at,
                    task.expires_at,
                    task.version,
                    self._payload(task),
                ),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT payload FROM bdlh_runtime_financial_task WHERE task_id = %s",
                    (task.task_id,),
                ).fetchone()
            if row is None:
                raise RuntimeError("task create failed")
            return self._decode(row[0])

    def update(self, task: FinancialTask, *, expected_version: int) -> FinancialTask:
        updated = task.model_copy(deep=True)
        updated.version = expected_version + 1
        with self._connect() as connection:
            row = connection.execute(
                """
                UPDATE bdlh_runtime_financial_task
                SET status = %s, next_wakeup_at = %s, expires_at = %s,
                    version = %s, payload = %s::jsonb, updated_at = CURRENT_TIMESTAMP
                WHERE task_id = %s AND user_id = %s AND version = %s
                RETURNING payload
                """,
                (
                    updated.status.value,
                    updated.next_wakeup_at,
                    updated.expires_at,
                    updated.version,
                    self._payload(updated),
                    updated.task_id,
                    updated.authenticated_user_id,
                    expected_version,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("TASK_VERSION_CONFLICT")
            return self._decode(row[0])

    def get(self, task_id: str, authenticated_user_id: str) -> FinancialTask | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM bdlh_runtime_financial_task WHERE task_id = %s AND user_id = %s",
                (task_id, authenticated_user_id),
            ).fetchone()
            return self._decode(row[0]) if row else None

    def list_for_user(self, authenticated_user_id: str, *, limit: int = 100) -> list[FinancialTask]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM bdlh_runtime_financial_task
                WHERE user_id = %s ORDER BY updated_at DESC LIMIT %s
                """,
                (authenticated_user_id, max(1, limit)),
            ).fetchall()
            return [self._decode(row[0]) for row in rows]

    def claim_due(self, *, now: datetime, limit: int) -> list[tuple[FinancialTask, str]]:
        timestamp = _aware(now, "now")
        claimed: list[tuple[FinancialTask, str]] = []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT task_id, payload FROM bdlh_runtime_financial_task
                WHERE status IN ('SCHEDULED', 'WAITING')
                  AND next_wakeup_at <= %s AND expires_at > %s
                ORDER BY next_wakeup_at
                FOR UPDATE SKIP LOCKED LIMIT %s
                """,
                (timestamp, timestamp, max(1, limit)),
            ).fetchall()
            for task_id, payload in rows:
                task = self._decode(payload)
                scheduled_for = task.next_wakeup_at.astimezone(UTC).isoformat()
                wakeup_key = f"{task.task_id}:{scheduled_for}"
                inserted = connection.execute(
                    """
                    INSERT INTO bdlh_runtime_task_wakeup(task_id, wakeup_key, scheduled_for)
                    VALUES (%s, %s, %s) ON CONFLICT (wakeup_key) DO NOTHING
                    RETURNING wakeup_key
                    """,
                    (task.task_id, wakeup_key, task.next_wakeup_at),
                ).fetchone()
                if inserted is None:
                    continue
                task.last_wakeup_at = timestamp
                task.transition(
                    FinancialTaskStatus.RUNNING,
                    reason_code="SCHEDULED_WAKEUP_CLAIMED",
                    now=timestamp,
                    wakeup_key=wakeup_key,
                )
                task.version += 1
                connection.execute(
                    """
                    UPDATE bdlh_runtime_financial_task
                    SET status = 'RUNNING', version = %s, payload = %s::jsonb,
                        updated_at = CURRENT_TIMESTAMP WHERE task_id = %s
                    """,
                    (task.version, self._payload(task), task_id),
                )
                claimed.append((task, wakeup_key))
        return claimed

    def expire_due(self, *, now: datetime) -> int:
        timestamp = _aware(now, "now")
        count = 0
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT task_id, payload FROM bdlh_runtime_financial_task
                WHERE status IN ('SCHEDULED', 'WAITING') AND expires_at <= %s
                FOR UPDATE SKIP LOCKED
                """,
                (timestamp,),
            ).fetchall()
            for task_id, payload in rows:
                task = self._decode(payload)
                wakeup_key = f"{task.task_id}:{task.next_wakeup_at.astimezone(UTC).isoformat()}"
                connection.execute(
                    "DELETE FROM bdlh_runtime_task_wakeup WHERE wakeup_key = %s",
                    (wakeup_key,),
                )
                task.transition(
                    FinancialTaskStatus.EXPIRED,
                    reason_code="TASK_EXPIRY_REACHED",
                    now=timestamp,
                )
                task.version += 1
                connection.execute(
                    """
                    UPDATE bdlh_runtime_financial_task SET status = 'EXPIRED',
                        version = %s, payload = %s::jsonb, updated_at = CURRENT_TIMESTAMP
                    WHERE task_id = %s
                    """,
                    (task.version, self._payload(task), task_id),
                )
                count += 1
        return count

    def recover_stale(self, *, now: datetime, stale_before: datetime) -> int:
        timestamp = _aware(now, "now")
        cutoff = _aware(stale_before, "stale_before")
        count = 0
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT task_id, payload FROM bdlh_runtime_financial_task
                WHERE status = 'RUNNING' AND updated_at <= %s
                FOR UPDATE SKIP LOCKED
                """,
                (cutoff,),
            ).fetchall()
            for task_id, payload in rows:
                task = self._decode(payload)
                wakeup_key = f"{task.task_id}:{task.next_wakeup_at.astimezone(UTC).isoformat()}"
                # 与 InMemoryTaskStore 对齐：释放幂等槽位，便于陈旧恢复后
                # claim_due 能重新插入同一 wakeup_key。
                connection.execute(
                    "DELETE FROM bdlh_runtime_task_wakeup WHERE wakeup_key = %s",
                    (wakeup_key,),
                )
                task.transition(
                    FinancialTaskStatus.WAITING,
                    reason_code="STALE_WAKEUP_RECOVERED",
                    now=timestamp,
                )
                task.version += 1
                connection.execute(
                    """
                    UPDATE bdlh_runtime_financial_task SET status = 'WAITING',
                        next_wakeup_at = %s, version = %s, payload = %s::jsonb,
                        updated_at = CURRENT_TIMESTAMP WHERE task_id = %s
                    """,
                    (task.next_wakeup_at, task.version, self._payload(task), task_id),
                )
                count += 1
        return count


class PostgresNotificationOutbox:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        PostgresTaskStore._validate_dependency()
        self._validate_schema()

    def _connect(self):
        import psycopg

        return psycopg.connect(self._dsn)

    def _validate_schema(self) -> None:
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT to_regclass('public.bdlh_runtime_notification_outbox')").fetchone()
        except Exception as exc:
            raise ConfigurationError(f"PostgreSQL Notification Outbox 初始化失败: {exc}") from exc
        if row is None or row[0] is None:
            raise ConfigurationError("缺少 M6 PostgreSQL migration: 20260812_financial_tasks.sql")

    @staticmethod
    def _decode(payload: object) -> NotificationOutboxMessage:
        if isinstance(payload, str):
            payload = json.loads(payload)
        return NotificationOutboxMessage.model_validate(payload)

    def enqueue(self, message: NotificationOutboxMessage) -> NotificationOutboxMessage:
        with self._connect() as connection:
            row = connection.execute(
                """
                INSERT INTO bdlh_runtime_notification_outbox(
                    outbox_id, task_id, user_id, idempotency_key, status, payload
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (idempotency_key) DO UPDATE
                    SET idempotency_key = EXCLUDED.idempotency_key
                RETURNING payload
                """,
                (
                    message.outbox_id,
                    message.task_id,
                    message.authenticated_user_id,
                    message.idempotency_key,
                    message.status.value,
                    message.model_dump_json(),
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("notification enqueue failed")
            return self._decode(row[0])

    def claim_pending(self, *, limit: int) -> list[NotificationOutboxMessage]:
        claimed: list[NotificationOutboxMessage] = []
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE bdlh_runtime_notification_outbox
                SET status = 'FAILED',
                    payload = jsonb_set(
                        jsonb_set(payload, '{status}', '"FAILED"'::jsonb),
                        '{last_error}', '"STALE_SEND_RECOVERED"'::jsonb
                    ),
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'SENDING'
                  AND updated_at <= CURRENT_TIMESTAMP - INTERVAL '5 minutes'
                """
            )
            rows = connection.execute(
                """
                SELECT outbox_id, payload FROM bdlh_runtime_notification_outbox
                WHERE status IN ('PENDING', 'FAILED')
                  AND COALESCE((payload->>'attempts')::int, 0) < 3
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED LIMIT %s
                """,
                (max(1, limit),),
            ).fetchall()
            for outbox_id, payload in rows:
                message = self._decode(payload)
                message.status = NotificationStatus.SENDING
                message.attempts += 1
                connection.execute(
                    """
                    UPDATE bdlh_runtime_notification_outbox
                    SET status = 'SENDING', payload = %s::jsonb, updated_at = CURRENT_TIMESTAMP
                    WHERE outbox_id = %s
                    """,
                    (message.model_dump_json(), outbox_id),
                )
                claimed.append(message)
        return claimed

    def mark_sent(self, outbox_id: str, *, sent_at: datetime) -> NotificationOutboxMessage:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM bdlh_runtime_notification_outbox WHERE outbox_id = %s FOR UPDATE",
                (outbox_id,),
            ).fetchone()
            if row is None:
                raise KeyError(outbox_id)
            message = self._decode(row[0])
            if message.status != NotificationStatus.SENT:
                message.status = NotificationStatus.SENT
                message.sent_at = _aware(sent_at, "sent_at")
                message.last_error = None
                connection.execute(
                    """
                    UPDATE bdlh_runtime_notification_outbox
                    SET status = 'SENT', payload = %s::jsonb, updated_at = CURRENT_TIMESTAMP
                    WHERE outbox_id = %s
                    """,
                    (message.model_dump_json(), outbox_id),
                )
            return message

    def mark_failed(self, outbox_id: str, *, error: str) -> NotificationOutboxMessage:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM bdlh_runtime_notification_outbox WHERE outbox_id = %s FOR UPDATE",
                (outbox_id,),
            ).fetchone()
            if row is None:
                raise KeyError(outbox_id)
            message = self._decode(row[0])
            message.status = NotificationStatus.FAILED
            message.last_error = str(error)[:500]
            connection.execute(
                """
                UPDATE bdlh_runtime_notification_outbox
                SET status = 'FAILED', payload = %s::jsonb, updated_at = CURRENT_TIMESTAMP
                WHERE outbox_id = %s
                """,
                (message.model_dump_json(), outbox_id),
            )
            return message

    def list_for_user(self, authenticated_user_id: str, *, limit: int = 100) -> list[NotificationOutboxMessage]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM bdlh_runtime_notification_outbox
                WHERE user_id = %s AND status = 'SENT'
                ORDER BY updated_at DESC LIMIT %s
                """,
                (authenticated_user_id, max(1, limit)),
            ).fetchall()
            return [self._decode(row[0]) for row in rows]


def create_task_store(*, environment: str = "production") -> TaskStore:
    """产品工厂禁止返回内存 Task Store；请经 Java Data Plane。

    ``InMemoryTaskStore`` 仍可供测试直接构造；隔离装配见
    ``tests/helpers_application``。
    """

    del environment
    raise ConfigurationError("Python 内存 Financial Task Store 已禁用；请使用 Java Data Plane")


def create_notification_outbox(*, environment: str = "production") -> NotificationOutbox:
    """产品工厂禁止返回内存 Outbox；请经 Java Data Plane。

    ``InMemoryNotificationOutbox`` 仍可供测试直接构造；隔离装配见
    ``tests/helpers_application``。
    """

    del environment
    raise ConfigurationError("Python 内存 Notification Outbox 已禁用；请使用 Java Data Plane")


def new_task_id() -> str:
    return str(uuid4())


def task_id_from_idempotency(authenticated_user_id: str, idempotency_key: str) -> str:
    """相同用户和创建幂等键稳定映射到同一 task_id。"""

    return str(uuid5(NAMESPACE_URL, f"bdlh:financial-task:{authenticated_user_id}:{idempotency_key}"))


def new_outbox_id() -> str:
    return str(uuid4())
