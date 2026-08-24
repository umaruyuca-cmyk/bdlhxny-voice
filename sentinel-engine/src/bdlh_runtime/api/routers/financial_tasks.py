"""financial-tasks 路由：M6 持续任务创建/查询/取消（重构方案 D1/P3：自 routes.py 拆出）。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from ..context import ApiContext
from ..schemas import CreateFinancialTaskRequest


def register(router: APIRouter, ctx: ApiContext) -> None:
    application = ctx.application

    @router.post("/financial-tasks", status_code=201)
    async def create_financial_task(
        payload: CreateFinancialTaskRequest,
        authorization: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        from bdlh_runtime.infra.tasks import (
            FinancialTask,
            FinancialTaskStatus,
            PriceThresholdCondition,
            TaskAuditEvent,
            task_id_from_idempotency,
            utc_now,
        )

        user_id = ctx.authenticated_task_user(authorization)
        normalized_key = str(idempotency_key or "").strip()
        if not normalized_key or len(normalized_key) > 255:
            raise HTTPException(
                status_code=422,
                detail="创建持续任务必须提供 1..255 字符的 Idempotency-Key",
            )
        now = utc_now()
        first_wakeup_at = payload.first_wakeup_at or now
        if first_wakeup_at.tzinfo is None or payload.expires_at.tzinfo is None:
            raise HTTPException(status_code=422, detail="任务时间必须包含时区")
        first_wakeup_at = first_wakeup_at.astimezone(UTC)
        expires_at = payload.expires_at.astimezone(UTC)
        if expires_at <= now or first_wakeup_at >= expires_at:
            raise HTTPException(
                status_code=422,
                detail="expires_at 必须晚于当前时间和 first_wakeup_at",
            )
        fingerprint_payload = payload.model_dump(mode="json")
        creation_fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        task_id = task_id_from_idempotency(user_id, normalized_key)
        task = FinancialTask(
            task_id=task_id,
            authenticated_user_id=user_id,
            status=FinancialTaskStatus.SCHEDULED,
            condition=PriceThresholdCondition(
                symbol=payload.symbol.strip().upper(),
                market=payload.market.strip().upper(),
                instrument_name=payload.instrument_name,
                direction=payload.direction,
                threshold=payload.threshold,
                currency=payload.currency.strip().upper(),
            ),
            confirmation_ref=f"task-confirmation:{task_id}",
            creation_fingerprint=creation_fingerprint,
            cadence_seconds=payload.cadence_seconds,
            next_wakeup_at=first_wakeup_at,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
            audit_events=[
                TaskAuditEvent(
                    event_type="task.scheduled",
                    occurred_at=now,
                    reason_code="USER_CONFIRMED_PRICE_OBSERVATION",
                    details={"confirmation_ref": f"task-confirmation:{task_id}"},
                )
            ],
        )
        created = application.task_store.create(task)
        if created.creation_fingerprint != creation_fingerprint:
            raise HTTPException(
                status_code=409,
                detail="同一 Idempotency-Key 已用于不同的任务创建请求",
            )
        return created.model_dump(mode="json")

    @router.get("/financial-tasks")
    async def list_financial_tasks(
        authorization: str | None = Header(default=None),
        limit: int = Query(default=50, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        user_id = ctx.authenticated_task_user(authorization)
        return [task.model_dump(mode="json") for task in application.task_store.list_for_user(user_id, limit=limit)]

    @router.get("/financial-tasks/{task_id}")
    async def get_financial_task(
        task_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        user_id = ctx.authenticated_task_user(authorization)
        task = application.task_store.get(task_id, user_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return task.model_dump(mode="json")

    @router.post("/financial-tasks/{task_id}/cancel")
    async def cancel_financial_task(
        task_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        from bdlh_runtime.infra.tasks import TERMINAL_TASK_STATUSES, FinancialTaskStatus, utc_now

        user_id = ctx.authenticated_task_user(authorization)
        task = application.task_store.get(task_id, user_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.status in TERMINAL_TASK_STATUSES:
            if task.status == FinancialTaskStatus.CANCELLED:
                return task.model_dump(mode="json")
            raise HTTPException(status_code=409, detail=f"任务已处于终态 {task.status.value}")
        if task.status in {
            FinancialTaskStatus.RUNNING,
            FinancialTaskStatus.TRIGGERED,
        }:
            raise HTTPException(
                status_code=409,
                detail="任务正在执行当前唤醒，请在本轮结束后重试取消",
            )
        expected_version = task.version
        task.transition(
            FinancialTaskStatus.CANCELLED,
            reason_code="USER_CANCELLED_TASK",
            now=utc_now(),
        )
        try:
            cancelled = application.task_store.update(task, expected_version=expected_version)
        except RuntimeError as exc:
            if str(exc) != "TASK_VERSION_CONFLICT":
                raise
            current = application.task_store.get(task_id, user_id)
            if current is None:
                raise HTTPException(status_code=404, detail="任务不存在") from exc
            if current.status == FinancialTaskStatus.CANCELLED:
                return current.model_dump(mode="json")
            if current.status in {
                FinancialTaskStatus.RUNNING,
                FinancialTaskStatus.TRIGGERED,
            }:
                raise HTTPException(
                    status_code=409,
                    detail="任务正在执行当前唤醒，请在本轮结束后重试取消",
                ) from exc
            if current.status in TERMINAL_TASK_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail=f"任务已处于终态 {current.status.value}",
                ) from exc
            retry_version = current.version
            current.transition(
                FinancialTaskStatus.CANCELLED,
                reason_code="USER_CANCELLED_TASK",
                now=utc_now(),
            )
            try:
                cancelled = application.task_store.update(current, expected_version=retry_version)
            except RuntimeError as retry_exc:
                if str(retry_exc) != "TASK_VERSION_CONFLICT":
                    raise
                raise HTTPException(
                    status_code=409,
                    detail="任务状态已变更，请重试取消",
                ) from retry_exc
        return cancelled.model_dump(mode="json")
