"""notifications 路由：通知外发箱查询（重构方案 D1/P3：自 routes.py 拆出）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Query

from ..context import ApiContext


def register(router: APIRouter, ctx: ApiContext) -> None:
    @router.get("/notifications")
    async def list_notifications(
        authorization: str | None = Header(default=None),
        limit: int = Query(default=50, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        user_id = ctx.authenticated_task_user(authorization)
        return [
            message.model_dump(mode="json")
            for message in ctx.application.notification_outbox.list_for_user(user_id, limit=limit)
        ]
