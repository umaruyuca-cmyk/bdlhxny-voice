"""agent-runs 路由：创建/读取/恢复/事件流（重构方案 D1/P3：自 routes.py 拆出）。"""

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
from bdlh_runtime.runtime.turn_router import TurnDecision, TurnRoute, is_resume_signal, resolve_resume_message

from ..context import ApiContext
from ..projections import CognitiveExecutionObserverAdapter, cognitive_state, public_state
from ..schemas import CancelAckResponse, PauseAckResponse, ResumeRequest, RunRequest, RunResponse
from ..sse import encode_event

logger = logging.getLogger("bdlh_runtime.api.routers.agent_runs")


def register(router: APIRouter, ctx: ApiContext) -> None:
    application = ctx.application

    @router.post("/agent-runs")
    async def create_run(
        payload: RunRequest,
        authorization: str | None = Header(default=None),
    ) -> RunResponse:
        """创建并运行新的 Cognitive 线程。thread_id 可选，传入则延续已有会话。"""
        user_id = ctx.request_user_id(authorization, payload.user_id)
        run_id = str(uuid4())
        public_thread_id = payload.thread_id or run_id
        progress = CognitiveExecutionProgress()
        logger.info(
            "runtime_path_selected path=%s reason=%s run_id=%s thread_id=%s",
            COGNITIVE_RUNTIME_PATH,
            "COGNITIVE_ONLY",
            run_id,
            public_thread_id,
        )
        if application.run_registry is not None:
            application.run_registry.register(
                RunLocation(
                    run_id=run_id,
                    thread_id=public_thread_id,
                    user_id=user_id,
                    runtime_path=COGNITIVE_RUNTIME_PATH,
                )
            )
        try:
            execution = await application.cognitive_application.run(
                InputEvent(
                    event_id=f"run:{run_id}",
                    run_id=run_id,
                    user_id=str(user_id),
                    session_id=public_thread_id,
                    message=payload.message,
                ),
                observer=CognitiveExecutionObserverAdapter(progress),
            )
        except Exception:
            logger.exception("Cognitive agent-run 执行失败 run_id=%s", run_id)
            failed_state = {
                "run_id": run_id,
                "thread_id": public_thread_id,
                "user_id": user_id,
                "runtime_path": COGNITIVE_RUNTIME_PATH,
                "status": "FAILED",
                "next_stage": "completed",
                "final_response": {
                    "response_kind": "BLOCKED",
                    "response_structure": "SAFETY_BLOCK",
                    "message": "分析流程执行失败，请稍后重试。",
                    "audit_codes": ["COGNITIVE_EXECUTION_FAILED"],
                },
                "events": [],
            }
            ctx.store.save(run_id, user_id, failed_state)
            return public_state(run_id, failed_state)
        state = cognitive_state(run_id, public_thread_id, execution.response, user_id)
        ctx.store.save(run_id, user_id, state)
        return public_state(run_id, state)

    @router.get("/agent-runs/{run_id}")
    async def get_run(
        run_id: str,
        authorization: str | None = Header(default=None),
    ) -> RunResponse:
        requester_user_id = ctx.request_user_id(authorization)
        state = await ctx.load_run_state(run_id, requester_user_id)
        if state is None:
            raise HTTPException(status_code=404, detail="run not found")
        ctx.authorize_run(run_id, requester_user_id, state)
        return public_state(run_id, state)

    @router.post("/agent-runs/{run_id}/pause")
    async def pause_run(
        run_id: str,
        authorization: str | None = Header(default=None),
    ) -> PauseAckResponse:
        """用户 Esc → Pause：协作式停止并写入可恢复 pending（ADR-014）。"""
        requester_user_id = ctx.request_user_id(authorization)
        state = await ctx.load_run_state(run_id, requester_user_id)
        location = (
            application.run_registry.get(run_id, requester_user_id) if application.run_registry is not None else None
        )
        if state is None and location is None:
            raise HTTPException(status_code=404, detail="run not found")
        if state is not None:
            ctx.authorize_run(run_id, requester_user_id, state)
        elif location is not None and str(location.user_id) != str(requester_user_id):
            raise HTTPException(status_code=404, detail="run not found")

        status = str((state or {}).get("status") or "")
        if status in {"COMPLETED", "SUCCESS", "FAILED", "CANCELLED", "ABANDONED"}:
            raise HTTPException(status_code=409, detail="run is not pausable")

        if application.run_control is not None:
            application.run_control.request_pause(run_id)

        session_id = (
            (location.thread_id if location is not None else None)
            or (state or {}).get("thread_id")
            or (state or {}).get("session_id")
        )
        checkpoint_id = location.checkpoint_id if location is not None else (state or {}).get("checkpoint_id")
        chat_sessions = getattr(application, "chat_session_store", None) or ctx.chat_sessions
        if session_id and chat_sessions is not None:
            try:
                chat_sessions.ensure(str(session_id), requester_user_id)
                chat_sessions.set_pending(
                    str(session_id),
                    requester_user_id,
                    run_id=run_id,
                    thread_id=str(session_id),
                    checkpoint_id=checkpoint_id,
                    runtime_path=COGNITIVE_RUNTIME_PATH,
                    pause_reason="user_pause",
                    awaiting_route_confirm=False,
                )
            except KeyError:
                logger.warning("pause: chat session missing session_id=%s run_id=%s", session_id, run_id)

        paused_state = {
            "run_id": run_id,
            "thread_id": session_id,
            "user_id": requester_user_id,
            "runtime_path": COGNITIVE_RUNTIME_PATH,
            "status": "PAUSED_BY_USER",
            "next_stage": "paused",
            "final_response": {
                "response_kind": "ASK_USER",
                "response_structure": "CLARIFICATION",
                "message": "已按你的操作暂停。回复「继续」可接着刚才的分析，或直接提出新的问题。",
                "audit_codes": ["PAUSED_BY_USER"],
            },
            "events": list((state or {}).get("events") or [])
            + [{"type": "run.paused", "status": "PAUSED_BY_USER", "resumable": True}],
            "checkpoint_id": checkpoint_id,
        }
        ctx.store.save(run_id, requester_user_id, paused_state)
        return PauseAckResponse(
            runId=run_id,
            sessionId=str(session_id) if session_id else None,
            status="PAUSED_BY_USER",
            checkpointId=checkpoint_id,
            resumable=True,
        )

    @router.post("/agent-runs/{run_id}/cancel")
    async def cancel_run(
        run_id: str,
        authorization: str | None = Header(default=None),
    ) -> CancelAckResponse:
        """放弃当前 run：清 pending，标记 ABANDONED，不可 resume。"""
        requester_user_id = ctx.request_user_id(authorization)
        state = await ctx.load_run_state(run_id, requester_user_id)
        location = (
            application.run_registry.get(run_id, requester_user_id) if application.run_registry is not None else None
        )
        if state is None and location is None:
            raise HTTPException(status_code=404, detail="run not found")
        if state is not None:
            ctx.authorize_run(run_id, requester_user_id, state)
        elif location is not None and str(location.user_id) != str(requester_user_id):
            raise HTTPException(status_code=404, detail="run not found")

        status = str((state or {}).get("status") or "")
        if status in {"COMPLETED", "SUCCESS", "FAILED", "CANCELLED", "ABANDONED"}:
            raise HTTPException(status_code=409, detail="run is not cancellable")

        if application.run_control is not None:
            application.run_control.request_pause(run_id)
            application.run_control.clear(run_id)

        session_id = (
            (location.thread_id if location is not None else None)
            or (state or {}).get("thread_id")
            or (state or {}).get("session_id")
        )
        chat_sessions = getattr(application, "chat_session_store", None) or ctx.chat_sessions
        if session_id and chat_sessions is not None:
            try:
                session = chat_sessions.get(str(session_id), requester_user_id)
                if session is not None and str(session.pending_run_id or "") == str(run_id):
                    chat_sessions.set_pending(
                        str(session_id),
                        requester_user_id,
                        run_id=None,
                        thread_id=None,
                        checkpoint_id=None,
                        runtime_path=None,
                    )
            except KeyError:
                logger.warning("cancel: chat session missing session_id=%s run_id=%s", session_id, run_id)

        abandoned_state = {
            "run_id": run_id,
            "thread_id": session_id,
            "user_id": requester_user_id,
            "runtime_path": COGNITIVE_RUNTIME_PATH,
            "status": "ABANDONED",
            "next_stage": "completed",
            "final_response": {
                "response_kind": "ANSWER",
                "response_structure": "CLARIFICATION",
                "message": "已取消刚才的分析。可以直接提出新的问题。",
                "audit_codes": ["ABANDONED_BY_USER"],
            },
            "events": list((state or {}).get("events") or [])
            + [{"type": "run.abandoned", "status": "ABANDONED", "resumable": False}],
            "checkpoint_id": None,
        }
        ctx.store.save(run_id, requester_user_id, abandoned_state)
        return CancelAckResponse(
            runId=run_id,
            sessionId=str(session_id) if session_id else None,
            status="ABANDONED",
            resumable=False,
        )

    @router.post("/agent-runs/{run_id}/resume")
    async def resume_run(
        run_id: str,
        payload: ResumeRequest,
        authorization: str | None = Header(default=None),
    ) -> RunResponse:
        """使用同一 Cognitive session/run 恢复用户补充后的运行。"""
        requester_user_id = ctx.request_user_id(authorization)
        state_before_resume = await ctx.load_run_state(run_id, requester_user_id)
        if state_before_resume is None:
            raise HTTPException(status_code=404, detail="run not found")
        ctx.authorize_run(run_id, requester_user_id, state_before_resume)
        location = (
            application.run_registry.get(run_id, requester_user_id) if application.run_registry is not None else None
        )
        thread_id = location.thread_id if location is not None else state_before_resume.get("thread_id")
        user_id = location.user_id if location is not None else state_before_resume.get("user_id")
        message = (
            payload.value
            if isinstance(payload.value, str)
            else str(payload.value.get("message") or payload.value.get("symbol") or "").strip()
        )
        if not message:
            raise HTTPException(status_code=422, detail="resume value 缺少 message 或 symbol")
        chat_sessions = getattr(application, "chat_session_store", None) or ctx.chat_sessions
        session = chat_sessions.get(str(thread_id), str(user_id)) if thread_id and chat_sessions else None
        prior_user_messages = (
            [item.content for item in session.messages if item.role == "user"] if session is not None else []
        )
        resume_route = TurnRoute(
            decision=TurnDecision.RESUME,
            reason="STRONG_RESUME" if is_resume_signal(message) else "CLARIFICATION_ANSWER",
            pending_run_id=run_id,
        )
        cognitive_message = resolve_resume_message(
            user_message=message,
            route=resume_route,
            prior_user_messages=prior_user_messages,
        )
        progress = CognitiveExecutionProgress()
        try:
            execution = await application.cognitive_application.run(
                InputEvent(
                    event_id=f"resume:{run_id}:{uuid4()}",
                    run_id=run_id,
                    user_id=str(user_id),
                    session_id=thread_id or run_id,
                    message=cognitive_message,
                ),
                observer=CognitiveExecutionObserverAdapter(progress),
            )
        except Exception:
            logger.exception("Cognitive run 恢复失败 run_id=%s", run_id)
            failed_state = {
                "run_id": run_id,
                "thread_id": thread_id,
                "user_id": user_id,
                "runtime_path": COGNITIVE_RUNTIME_PATH,
                "status": "FAILED",
                "next_stage": "completed",
                "final_response": {
                    "response_kind": "BLOCKED",
                    "response_structure": "SAFETY_BLOCK",
                    "message": "恢复执行失败，请稍后重试。",
                    "audit_codes": ["COGNITIVE_RESUME_FAILED"],
                },
                "events": [],
            }
            ctx.store.save(run_id, user_id, failed_state)
            return public_state(run_id, failed_state)
        state = cognitive_state(
            run_id,
            thread_id or run_id,
            execution.response,
            user_id,
        )
        ctx.store.save(run_id, user_id, state)
        return public_state(run_id, state)

    async def event_stream(run_id: str, requester_user_id: str | None) -> AsyncIterator[str]:
        index = 0
        while True:
            state = await ctx.load_run_state(run_id, requester_user_id)
            if state is None:
                yield encode_event("error", {"message": "run not found"})
                return
            events = state.get("events", [])
            while index < len(events):
                yield encode_event("workflow", events[index])
                index += 1
            if state.get("final_response") or state.get("__interrupt__"):
                return
            await asyncio.sleep(0.1)

    @router.get("/agent-runs/{run_id}/events")
    async def stream_events(
        run_id: str,
        authorization: str | None = Header(default=None),
    ):
        requester_user_id = ctx.request_user_id(authorization)
        state = await ctx.load_run_state(run_id, requester_user_id)
        if state is None:
            raise HTTPException(status_code=404, detail="run not found")
        ctx.authorize_run(run_id, requester_user_id, state)
        return StreamingResponse(
            event_stream(run_id, requester_user_id),
            media_type="text/event-stream",
        )
