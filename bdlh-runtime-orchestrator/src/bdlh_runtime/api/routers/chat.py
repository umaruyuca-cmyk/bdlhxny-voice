"""chat 路由：单助手页面入口（重构方案 D1/P3：自 routes.py 拆出）。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from bdlh_runtime.cognitive.contracts import InputEvent
from bdlh_runtime.runtime.run_registry import RunLocation
from bdlh_runtime.runtime.runtime_path import COGNITIVE_RUNTIME_PATH, CognitiveExecutionProgress

from ..context import ApiContext
from ..projections import CognitiveExecutionObserverAdapter, chat_answer_text, cognitive_state
from ..schemas import ChatRequest
from ..sse import encode_event

logger = logging.getLogger("bdlh_runtime.api.routers.chat")


def register(router: APIRouter, ctx: ApiContext) -> None:
    application = ctx.application
    chat_sessions = ctx.chat_sessions

    @router.post("/chat/stream")
    async def chat_stream(
        payload: ChatRequest,
        authorization: str | None = Header(default=None),
    ) -> StreamingResponse:
        """单助手页面入口：鉴权后把一轮消息交给 Cognitive。"""

        user_id = ctx.request_user_id(authorization)
        message = payload.message.strip()
        if not message:
            raise HTTPException(status_code=422, detail="message 不能为空")

        session = chat_sessions.ensure(payload.session_id, user_id)
        if payload.regenerate:
            chat_sessions.prepare_regeneration(session.session_id, user_id)
        else:
            chat_sessions.add_message(session.session_id, user_id, "user", message)

        run_id = session.pending_run_id or str(uuid4())
        progress = CognitiveExecutionProgress()
        if application.run_registry is not None:
            application.run_registry.register(
                RunLocation(
                    run_id=run_id,
                    thread_id=session.session_id,
                    user_id=user_id,
                    runtime_path=COGNITIVE_RUNTIME_PATH,
                )
            )
        logger.info(
            "runtime_path_selected path=%s reason=%s session_id=%s",
            COGNITIVE_RUNTIME_PATH,
            "PENDING_RUN_PATH_STICKY" if session.pending_run_id else "COGNITIVE_ONLY",
            session.session_id,
        )

        async def cognitive_chat_event_stream() -> AsyncIterator[str]:
            yield encode_event(
                "message",
                {
                    "schema_version": "1.0",
                    "type": "agent_run",
                    "runId": run_id,
                    "sessionId": session.session_id,
                    "runtimePath": COGNITIVE_RUNTIME_PATH,
                    "routingReason": "COGNITIVE_ONLY",
                },
            )
            yield encode_event(
                "message",
                {
                    "schema_version": "1.0",
                    "type": "status",
                    "step": "classifying",
                },
            )
            try:
                execution = await application.cognitive_application.run(
                    InputEvent(
                        event_id=f"chat:{run_id}",
                        run_id=run_id,
                        user_id=str(user_id),
                        session_id=session.session_id,
                        message=message,
                    ),
                    observer=CognitiveExecutionObserverAdapter(progress),
                )
            except Exception:
                logger.exception("Cognitive 聊天执行失败 run_id=%s", run_id)
                yield encode_event(
                    "message",
                    {
                        "schema_version": "1.0",
                        "type": "error",
                        "code": "COGNITIVE_EXECUTION_FAILED",
                        "message": "分析流程执行失败，请稍后重试。",
                    },
                )
                return

            response = execution.response
            ctx.store.save(run_id, user_id, cognitive_state(run_id, session.session_id, response, user_id))
            if response.response_kind == "ASK_USER":
                chat_sessions.set_pending(
                    session.session_id,
                    user_id,
                    run_id=run_id,
                    thread_id=session.session_id,
                    checkpoint_id=None,
                    runtime_path=COGNITIVE_RUNTIME_PATH,
                )
                yield encode_event(
                    "message",
                    {
                        "schema_version": "1.0",
                        "type": "clarification",
                        "prompt": response.message,
                        "options": response.next_steps,
                    },
                )
                yield encode_event(
                    "message",
                    {
                        "schema_version": "1.0",
                        "type": "done",
                        "status": "NEED_CLARIFICATION",
                        "sessionId": session.session_id,
                        "runId": run_id,
                        "runtimePath": COGNITIVE_RUNTIME_PATH,
                    },
                )
                return
            answer = chat_answer_text(response.model_dump(mode="json"))
            for start in range(0, len(answer), 24):
                yield encode_event(
                    "message",
                    {
                        "schema_version": "1.0",
                        "type": "token",
                        "content": answer[start : start + 24],
                    },
                )
                await asyncio.sleep(0)
            chat_sessions.add_message(session.session_id, user_id, "assistant", answer)
            chat_sessions.set_pending(
                session.session_id,
                user_id,
                run_id=None,
                thread_id=None,
                checkpoint_id=None,
                runtime_path=None,
            )
            blocked = response.response_kind in {
                "BLOCKED",
                "CAPABILITY_NOT_ENABLED",
            }
            yield encode_event(
                "message",
                {
                    "schema_version": "1.0",
                    "type": "done",
                    "status": "FAILED" if blocked else "COMPLETED",
                    "resultStatus": response.response_kind,
                    "sessionId": session.session_id,
                    "runId": run_id,
                    "runtimePath": COGNITIVE_RUNTIME_PATH,
                },
            )

        return StreamingResponse(
            cognitive_chat_event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
