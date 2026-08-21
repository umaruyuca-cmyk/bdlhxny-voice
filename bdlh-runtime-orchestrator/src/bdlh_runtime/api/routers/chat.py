"""chat 路由：单助手页面入口（重构方案 D1/P3：自 routes.py 拆出）。

ADR-014：有 pending 时先经 Turn Router，禁止盲目 resume。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from bdlh_runtime.cognitive.contracts import InputEvent
from bdlh_runtime.memory import MemoryWriter, recall_semantic_memory
from bdlh_runtime.runtime.run_registry import RunLocation
from bdlh_runtime.runtime.runtime_path import COGNITIVE_RUNTIME_PATH, CognitiveExecutionProgress
from bdlh_runtime.runtime.turn_router import (
    ASK_WHICH_PROMPT,
    TurnDecision,
    resolve_resume_message,
    route_turn,
)

from ..checkpoint_persistence import load_resume_checkpoint, persist_execution_checkpoint
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
        """单助手页面入口：鉴权后经 Turn Router，再交给 Cognitive。"""

        user_id = ctx.request_user_id(authorization)
        message = payload.message.strip()
        if not message:
            raise HTTPException(status_code=422, detail="message 不能为空")

        session = chat_sessions.ensure(payload.session_id, user_id)
        if payload.regenerate:
            chat_sessions.prepare_regeneration(session.session_id, user_id)
            chat_sessions.set_pending(
                session.session_id,
                user_id,
                run_id=None,
                thread_id=None,
                checkpoint_id=None,
                runtime_path=None,
            )
            session = chat_sessions.get(session.session_id, user_id) or session
        else:
            chat_sessions.add_message(session.session_id, user_id, "user", message)

        route = route_turn(
            message=message,
            pending_run_id=session.pending_run_id,
            awaiting_route_confirm=bool(session.awaiting_route_confirm),
        )

        if route.decision == TurnDecision.ASK_WHICH:
            return StreamingResponse(
                _ask_which_stream(chat_sessions, session.session_id, user_id, session.pending_run_id),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        if route.decision == TurnDecision.NEW_TURN:
            abandoned = session.pending_run_id
            chat_sessions.set_pending(
                session.session_id,
                user_id,
                run_id=None,
                thread_id=None,
                checkpoint_id=None,
                runtime_path=None,
            )
            if abandoned:
                abandoned_state = {
                    "run_id": abandoned,
                    "thread_id": session.session_id,
                    "user_id": user_id,
                    "runtime_path": COGNITIVE_RUNTIME_PATH,
                    "status": "ABANDONED",
                    "next_stage": "completed",
                    "final_response": {
                        "response_kind": "ANSWER",
                        "response_structure": "CLARIFICATION",
                        "message": "已取消刚才的分析。正在处理你的新问题。",
                        "audit_codes": ["ABANDONED_BY_USER"],
                    },
                    "events": [{"type": "run.abandoned", "status": "ABANDONED", "resumable": False}],
                    "checkpoint_id": None,
                }
                ctx.store.save(abandoned, user_id, abandoned_state)
                if application.run_control is not None:
                    application.run_control.clear(abandoned)
            run_id = str(uuid4())
            routing_reason = f"TURN_NEW:{route.reason}"
            resume_checkpoint_id = None
            logger.info(
                "turn_router decision=new_turn abandoned=%s new_run=%s reason=%s session_id=%s",
                abandoned,
                run_id,
                route.reason,
                session.session_id,
            )
        elif route.decision == TurnDecision.RESUME:
            run_id = str(session.pending_run_id)
            routing_reason = f"TURN_RESUME:{route.reason}"
            resume_checkpoint_id = session.pending_checkpoint_id
            chat_sessions.set_pending(
                session.session_id,
                user_id,
                run_id=session.pending_run_id,
                thread_id=session.pending_thread_id or session.session_id,
                checkpoint_id=session.pending_checkpoint_id,
                runtime_path=session.pending_runtime_path or COGNITIVE_RUNTIME_PATH,
                pause_reason=session.pause_reason,
                awaiting_route_confirm=False,
            )
            logger.info(
                "turn_router decision=resume run_id=%s reason=%s session_id=%s checkpoint_id=%s",
                run_id,
                route.reason,
                session.session_id,
                resume_checkpoint_id,
            )
        else:
            run_id = str(uuid4())
            routing_reason = "COGNITIVE_ONLY"
            resume_checkpoint_id = None
            logger.info(
                "runtime_path_selected path=%s reason=%s session_id=%s",
                COGNITIVE_RUNTIME_PATH,
                routing_reason,
                session.session_id,
            )

        # 「继续」等口令回放挂起前的真实用户目标；代码澄清答案仍用本句。
        session_after_route = chat_sessions.get(session.session_id, user_id) or session
        prior_user_messages = [
            item.content for item in session_after_route.messages if item.role == "user"
        ]
        cognitive_message = resolve_resume_message(
            user_message=message,
            route=route,
            prior_user_messages=prior_user_messages,
        )
        if cognitive_message != message:
            logger.info(
                "resume_message_restored session_id=%s from=%r to=%r",
                session.session_id,
                message,
                cognitive_message,
            )

        progress = CognitiveExecutionProgress()
        if application.run_registry is not None:
            application.run_registry.register(
                RunLocation(
                    run_id=run_id,
                    thread_id=session.session_id,
                    user_id=user_id,
                    checkpoint_id=resume_checkpoint_id if route.decision == TurnDecision.RESUME else None,
                    runtime_path=COGNITIVE_RUNTIME_PATH,
                )
            )
        if application.run_control is not None:
            application.run_control.clear(run_id)

        resume_checkpoint = None
        if route.decision == TurnDecision.RESUME:
            resume_checkpoint = load_resume_checkpoint(
                application=application,
                store=ctx.store,
                run_id=run_id,
                user_id=str(user_id),
                checkpoint_id=resume_checkpoint_id,
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
                    "routingReason": routing_reason,
                    "turnDecision": route.decision.value,
                    "checkpointId": resume_checkpoint.checkpoint_id if resume_checkpoint else None,
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
            memory_recall = await recall_semantic_memory(
                application.memory_store,
                user_id=str(user_id),
                query=cognitive_message,
                limit=5,
            )
            try:
                execution = await application.cognitive_application.run(
                    InputEvent(
                        event_id=f"chat:{run_id}",
                        run_id=run_id,
                        user_id=str(user_id),
                        session_id=session.session_id,
                        message=cognitive_message,
                    ),
                    observer=CognitiveExecutionObserverAdapter(progress),
                    checkpoint=resume_checkpoint,
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

            if memory_recall.degraded:
                yield encode_event(
                    "message",
                    {
                        "schema_version": "1.0",
                        "type": "status",
                        "step": "memory_degraded",
                        "limitation": memory_recall.limitation or "semantic_memory_degraded",
                    },
                )

            response = execution.response
            paused = "PAUSED_BY_USER" in response.audit_codes
            if response.response_kind == "ASK_USER":
                checkpoint_id = persist_execution_checkpoint(
                    application=application,
                    store=ctx.store,
                    chat_sessions=chat_sessions,
                    run_id=run_id,
                    session_id=session.session_id,
                    user_id=str(user_id),
                    execution=execution,
                    pause_reason="user_pause" if paused else "system_interrupt",
                )
                if paused:
                    yield encode_event(
                        "message",
                        {
                            "schema_version": "1.0",
                            "type": "run.paused",
                            "runId": run_id,
                            "sessionId": session.session_id,
                            "status": "PAUSED_BY_USER",
                            "resumable": True,
                            "checkpointId": checkpoint_id,
                        },
                    )
                else:
                    yield encode_event(
                        "message",
                        {
                            "schema_version": "1.0",
                            "type": "run.interrupted",
                            "runId": run_id,
                            "sessionId": session.session_id,
                            "status": "WAITING_USER",
                            "checkpointId": checkpoint_id,
                        },
                    )
                yield encode_event(
                    "message",
                    {
                        "schema_version": "1.0",
                        "type": "clarification",
                        "prompt": response.message,
                        "responseStructure": response.response_structure,
                        "options": _clarification_options(response.next_steps),
                    },
                )
                yield encode_event(
                    "message",
                    {
                        "schema_version": "1.0",
                        "type": "done",
                        "status": "PAUSED_BY_USER" if paused else "NEED_CLARIFICATION",
                        "sessionId": session.session_id,
                        "runId": run_id,
                        "runtimePath": COGNITIVE_RUNTIME_PATH,
                        "resumable": True,
                        "checkpointId": checkpoint_id,
                    },
                )
                return
            answer = chat_answer_text(response.model_dump(mode="json"))
            blocked = response.response_kind in {
                "BLOCKED",
                "CAPABILITY_NOT_ENABLED",
            }
            if blocked or "guardrail.blocked" in execution.state.public_events:
                yield encode_event(
                    "message",
                    {
                        "schema_version": "1.0",
                        "type": "guardrail.blocked",
                        "runId": run_id,
                        "sessionId": session.session_id,
                        "auditCode": (response.audit_codes[0] if response.audit_codes else "GUARDRAIL_BLOCKED"),
                        "ruleIds": list(response.rule_ids),
                        "message": response.message,
                        "responseKind": response.response_kind,
                    },
                )
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
            await _maybe_persist_confirmed_memory(
                application.memory_store,
                user_id=str(user_id),
                run_id=run_id,
                user_message=message,
            )
            ctx.store.save(
                run_id,
                user_id,
                cognitive_state(run_id, session.session_id, response, user_id),
            )
            # Esc pause 可能已写入 pending；完成路径不得盲目清掉可恢复书签。
            pause_requested = (
                application.run_control is not None and application.run_control.is_pause_requested(run_id)
            )
            if pause_requested:
                from bdlh_runtime.cognitive.checkpoint import build_checkpoint
                from bdlh_runtime.cognitive.contracts import PublicResponse
                from bdlh_runtime.cognitive.orchestrator import CognitiveExecution

                paused_response = PublicResponse(
                    response_kind="ASK_USER",
                    response_structure="CLARIFICATION",
                    message=answer,
                    audit_codes=list(dict.fromkeys([*response.audit_codes, "PAUSED_BY_USER"])),
                )
                checkpoint = execution.checkpoint or build_checkpoint(
                    run_id=run_id,
                    user_id=str(user_id),
                    state=execution.state,
                    pause_reason="user_pause",
                    resume_cursor="select",
                )
                persist_execution_checkpoint(
                    application=application,
                    store=ctx.store,
                    chat_sessions=chat_sessions,
                    run_id=run_id,
                    session_id=session.session_id,
                    user_id=str(user_id),
                    execution=CognitiveExecution(
                        state=execution.state,
                        response=paused_response,
                        checkpoint=checkpoint,
                    ),
                    pause_reason="user_pause",
                )
            else:
                chat_sessions.set_pending(
                    session.session_id,
                    user_id,
                    run_id=None,
                    thread_id=None,
                    checkpoint_id=None,
                    runtime_path=None,
                )
            if application.run_control is not None:
                application.run_control.clear(run_id)
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


async def _ask_which_stream(
    chat_sessions,
    session_id: str,
    user_id: str | None,
    pending_run_id: str | None,
) -> AsyncIterator[str]:
    session = chat_sessions.get(session_id, user_id)
    chat_sessions.set_pending(
        session_id,
        user_id,
        run_id=pending_run_id,
        thread_id=(session.pending_thread_id if session else None) or session_id,
        checkpoint_id=session.pending_checkpoint_id if session else None,
        runtime_path=(session.pending_runtime_path if session else None) or COGNITIVE_RUNTIME_PATH,
        pause_reason=session.pause_reason if session else "system_interrupt",
        awaiting_route_confirm=True,
    )
    chat_sessions.add_message(session_id, user_id, "assistant", ASK_WHICH_PROMPT)
    yield encode_event(
        "message",
        {
            "schema_version": "1.0",
            "type": "agent_run",
            "runId": pending_run_id,
            "sessionId": session_id,
            "runtimePath": COGNITIVE_RUNTIME_PATH,
            "routingReason": "TURN_ASK_WHICH",
            "turnDecision": TurnDecision.ASK_WHICH.value,
        },
    )
    yield encode_event(
        "message",
        {
            "schema_version": "1.0",
            "type": "token",
            "content": ASK_WHICH_PROMPT,
        },
    )
    yield encode_event(
        "message",
        {
            "schema_version": "1.0",
            "type": "done",
            "status": "ROUTE_CONFIRM",
            "sessionId": session_id,
            "runId": pending_run_id,
            "runtimePath": COGNITIVE_RUNTIME_PATH,
            "resumable": True,
        },
    )


def _clarification_options(next_steps: list[str] | None) -> list[dict[str, str]]:
    """把 PublicResponse.next_steps 投影为 Console ask-card 可点击选项。"""

    options: list[dict[str, str]] = []
    for step in next_steps or []:
        text = str(step or "").strip()
        if not text:
            continue
        label = text if len(text) <= 28 else text[:27] + "…"
        options.append({"label": label, "message": text})
    return options


def _confirmed_soft_preference(message: str) -> str | None:
    """仅当用户明确要求「确认记住」软偏好时提取；禁止把账本事实当记忆。"""
    text = (message or "").strip()
    if not text:
        return None
    markers = ("确认记住", "请记住我的偏好", "记住这个偏好", "confirm remember")
    if not any(marker in text.lower() if marker.isascii() else marker in text for marker in markers):
        return None
    if any(token in text for token in ("持仓", "账户余额", "风险等级", "下单", "password")):
        return None
    return text[:1200]


async def _maybe_persist_confirmed_memory(
    store: object | None,
    *,
    user_id: str,
    run_id: str,
    user_message: str,
) -> None:
    if store is None:
        return
    content = _confirmed_soft_preference(user_message)
    if content is None:
        return
    result = await MemoryWriter(store).persist(
        user_id=user_id,
        content=content,
        metadata={"knowledge_type": "confirmed", "run_id": run_id},
    )
    if result.degraded:
        logger.warning("memory_persist_degraded run_id=%s reason=%s", run_id, result.skipped_reason)
