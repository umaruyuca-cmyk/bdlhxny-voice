"""conversations 路由：会话目录读取/删除（重构方案 D1/P3：自 routes.py 拆出）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Response

from ..context import ApiContext


def register(router: APIRouter, ctx: ApiContext) -> None:
    chat_sessions = ctx.chat_sessions

    @router.get("/conversations")
    async def list_conversations(
        authorization: str | None = Header(default=None),
        limit: int = Query(default=30, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        """返回当前用户的会话目录。"""

        user_id = ctx.chat_user_id(authorization)
        return [
            {
                "sessionId": session.session_id,
                "title": session.title,
                "messageCount": len(session.messages),
                "updatedAt": session.updated_at.isoformat(),
            }
            for session in chat_sessions.list_for_user(user_id, limit)
        ]

    @router.get("/conversations/{session_id}")
    async def get_conversation(
        session_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        user_id = ctx.chat_user_id(authorization)
        session = chat_sessions.get(session_id, user_id)
        if session is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return {
            "session": {
                "sessionId": session.session_id,
                "title": session.title,
                "messageCount": len(session.messages),
                "updatedAt": session.updated_at.isoformat(),
            },
            "messages": [{"role": item.role, "content": item.content} for item in session.messages],
        }

    @router.delete("/conversations/{session_id}", status_code=204)
    async def delete_conversation(
        session_id: str,
        authorization: str | None = Header(default=None),
    ) -> Response:
        user_id = ctx.chat_user_id(authorization)
        if not chat_sessions.delete(session_id, user_id):
            raise HTTPException(status_code=404, detail="conversation not found")
        return Response(status_code=204)
