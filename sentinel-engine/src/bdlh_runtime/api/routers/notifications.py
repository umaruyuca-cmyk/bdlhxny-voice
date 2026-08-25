"""notifications 路由：通知外发箱查询 + 看护环追问闭环（WO-T1-6）。

重构方案 D1/P3：自 routes.py 拆出。WO-T1-6 新增 ``POST /notifications/{id}/followup``：
通知 → 创建携带事件上下文的追问会话 → 返回 session_id 供前端进入追问。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

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

    @router.post("/notifications/{notification_id}/followup")
    async def followup_notification(
        notification_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """追问入口：创建携带事件上下文的会话（设计文档 §4.8、§6.1、WO-T1-6）。

        - 鉴权：登录用户（游客不可追问，避免无主会话）；
        - 查通知：优先看护环 ``watch_notification_store``，回退 M6 ``notification_outbox``；
        - 建会话：经 ``create_followup_session`` 注入事件摘要为首轮 system 上下文；
        - 返回 ``session_id`` 与 ``event_summary`` 供前端直接进入追问抽屉。
        """
        user_id = ctx.authenticated_task_user(authorization)

        event_summary: str | None = None
        watch_store = getattr(ctx.application, "watch_notification_store", None)
        if watch_store is not None:
            notification = watch_store.get(notification_id)
            if notification is not None and str(notification.user_id) != str(user_id):
                raise HTTPException(status_code=403, detail="无权访问该通知")
            if notification is not None:
                # 通知标题即事件解读标题；含演示注入标记（C-4 透传）
                event_summary = notification.title or notification.event_summary

        if event_summary is None:
            # 回退 M6 outbox：追问通知也支持既有价格任务通知
            for message in ctx.application.notification_outbox.list_for_user(user_id, limit=200):
                if message.outbox_id == notification_id:
                    event_summary = message.title
                    break

        if event_summary is None:
            raise HTTPException(status_code=404, detail="通知不存在")

        # 延迟导入避免循环依赖（chat_sessions 在 infra/，notifications 在 api/）
        from bdlh_runtime.infra.chat_sessions import create_followup_session

        session = create_followup_session(
            ctx.chat_sessions,
            user_id=user_id,
            event_summary=event_summary,
        )
        return {"session_id": session.session_id, "event_summary": event_summary}
