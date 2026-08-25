"""API 层：把 CognitiveCheckpoint 写入 pending / Run State / Run Registry。"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.cognitive.checkpoint import (
    CognitiveCheckpoint,
    build_checkpoint,
    embed_checkpoint,
    extract_checkpoint,
    new_checkpoint_id,
)
from bdlh_runtime.cognitive.contracts import CognitiveExecution, CognitiveState, InputEvent
from bdlh_runtime.infra.run_registry import RunLocation
from bdlh_runtime.infra.runtime_path import COGNITIVE_RUNTIME_PATH

from .projections import cognitive_state


def _uid(user_id: str | None) -> str | None:
    if user_id is None:
        return None
    text = str(user_id).strip()
    return text or None


def persist_execution_checkpoint(
    *,
    application: Any,
    store: Any,
    chat_sessions: Any,
    run_id: str,
    session_id: str,
    user_id: str | None,
    execution: CognitiveExecution,
    pause_reason: str | None = None,
) -> str | None:
    """ASK_USER / Pause 路径写入非空 checkpoint_id；完成路径返回 None。"""
    owner = _uid(user_id)
    response = execution.response
    waiting = response.response_kind == "ASK_USER"
    paused = "PAUSED_BY_USER" in response.audit_codes
    if not waiting and not paused:
        return None

    reason = pause_reason or ("user_pause" if paused else "system_interrupt")
    checkpoint = execution.checkpoint
    if checkpoint is None:
        checkpoint = build_checkpoint(
            run_id=run_id,
            user_id=owner or "anonymous",
            state=execution.state,
            pause_reason="user_pause" if reason == "user_pause" else "system_interrupt",
            resume_cursor="select",
            original_message=execution.state.event.message,
        )
    run_payload = cognitive_state(
        run_id,
        session_id,
        response,
        owner,
        checkpoint_id=checkpoint.checkpoint_id,
        cognitive_checkpoint=checkpoint.model_dump(mode="json"),
    )
    store.save(run_id, owner, run_payload)
    if chat_sessions is not None:
        chat_sessions.ensure(session_id, owner)
        chat_sessions.set_pending(
            session_id,
            owner,
            run_id=run_id,
            thread_id=session_id,
            checkpoint_id=checkpoint.checkpoint_id,
            runtime_path=COGNITIVE_RUNTIME_PATH,
            pause_reason=reason,
            awaiting_route_confirm=False,
        )
    if application.run_registry is not None:
        application.run_registry.register(
            RunLocation(
                run_id=run_id,
                thread_id=session_id,
                user_id=owner,
                checkpoint_id=checkpoint.checkpoint_id,
                runtime_path=COGNITIVE_RUNTIME_PATH,
            )
        )
    return checkpoint.checkpoint_id


def load_resume_checkpoint(
    *,
    application: Any,
    store: Any,
    run_id: str,
    user_id: str | None,
    checkpoint_id: str | None,
) -> CognitiveCheckpoint | None:
    """按 pending_checkpoint_id / Run State 加载 L0 快照。"""
    owner = _uid(user_id)
    state = store.load(run_id, owner) if hasattr(store, "load") else None
    if state is None and application.run_state_reader is not None:
        state = application.run_state_reader.load(run_id, owner)
    checkpoint = extract_checkpoint(state)
    if checkpoint is not None:
        return checkpoint
    if not checkpoint_id:
        return None
    location = application.run_registry.get(run_id, owner) if application.run_registry is not None else None
    thread_id = (location.thread_id if location else None) or (state or {}).get("thread_id") or run_id
    message = ""
    final = (state or {}).get("final_response") if isinstance(state, dict) else None
    if isinstance(final, dict):
        message = str(final.get("message") or "")
    event = InputEvent(
        event_id=f"resume-seed:{run_id}",
        run_id=run_id,
        user_id=owner or "anonymous",
        session_id=str(thread_id),
        message=message or "继续",
    )
    return build_checkpoint(
        run_id=run_id,
        user_id=owner or "anonymous",
        state=CognitiveState(event=event),
        pause_reason="user_pause",
        checkpoint_id=checkpoint_id,
        resume_cursor="select",
        original_message=message or "继续",
    )


def mint_pause_checkpoint(
    *,
    application: Any,
    store: Any,
    chat_sessions: Any,
    run_id: str,
    session_id: str,
    user_id: str | None,
    existing_state: dict[str, Any] | None,
) -> CognitiveCheckpoint:
    """Esc Pause API：保证 pending 带非空 checkpoint_id。"""
    owner = _uid(user_id)
    existing = extract_checkpoint(existing_state)
    if existing is not None:
        checkpoint = existing
    else:
        checkpoint_id = (
            (existing_state or {}).get("checkpoint_id") if isinstance(existing_state, dict) else None
        ) or new_checkpoint_id(run_id)
        event = InputEvent(
            event_id=f"pause:{run_id}",
            run_id=run_id,
            user_id=owner or "anonymous",
            session_id=str(session_id),
            message=str(((existing_state or {}).get("final_response") or {}).get("message") or "已暂停"),
        )
        if isinstance(existing_state, dict) and isinstance(existing_state.get("cognitive_state"), dict):
            try:
                cog_state = CognitiveState.model_validate(existing_state["cognitive_state"])
            except Exception:  # noqa: BLE001
                cog_state = CognitiveState(event=event)
        else:
            cog_state = CognitiveState(event=event)
        checkpoint = build_checkpoint(
            run_id=run_id,
            user_id=owner or "anonymous",
            state=cog_state,
            pause_reason="user_pause",
            checkpoint_id=str(checkpoint_id),
            resume_cursor="select",
        )
    paused_state = {
        "run_id": run_id,
        "thread_id": session_id,
        "user_id": owner,
        "runtime_path": COGNITIVE_RUNTIME_PATH,
        "status": "PAUSED_BY_USER",
        "next_stage": "paused",
        "final_response": {
            "response_kind": "ASK_USER",
            "response_structure": "CLARIFICATION",
            "message": "已按你的操作暂停。回复「继续」可接着刚才的分析，或直接提出新的问题。",
            "audit_codes": ["PAUSED_BY_USER"],
        },
        "events": list((existing_state or {}).get("events") or [])
        + [{"type": "run.paused", "status": "PAUSED_BY_USER", "resumable": True}],
    }
    store.save(run_id, owner, embed_checkpoint(paused_state, checkpoint))
    if chat_sessions is not None:
        chat_sessions.ensure(session_id, owner)
        chat_sessions.set_pending(
            session_id,
            owner,
            run_id=run_id,
            thread_id=session_id,
            checkpoint_id=checkpoint.checkpoint_id,
            runtime_path=COGNITIVE_RUNTIME_PATH,
            pause_reason="user_pause",
            awaiting_route_confirm=False,
        )
    if application.run_registry is not None:
        application.run_registry.register(
            RunLocation(
                run_id=run_id,
                thread_id=session_id,
                user_id=owner,
                checkpoint_id=checkpoint.checkpoint_id,
                runtime_path=COGNITIVE_RUNTIME_PATH,
            )
        )
    return checkpoint
