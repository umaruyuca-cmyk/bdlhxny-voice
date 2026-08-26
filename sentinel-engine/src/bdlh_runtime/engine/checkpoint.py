"""Engine L0 Checkpoint（设计文档 §4.9、ADR-014 / G1）。

Pause / ASK_USER 必须写入非空 ``checkpoint_id``，并把可恢复的 CognitiveState
嵌入 Run State；Resume 从该快照续跑，禁止仅重放用户 objective。
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from bdlh_runtime.engine.contracts import CognitiveAction, CognitiveState

ResumeCursor = Literal["select", "dispatch", "after_domain"]


class CognitiveCheckpoint(BaseModel):
    """一次可恢复暂停的 L0 书签。"""

    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    pause_reason: Literal["system_interrupt", "user_pause"]
    original_message: str = Field(min_length=1)
    resume_cursor: ResumeCursor = "select"
    state: CognitiveState
    pending_action: CognitiveAction | None = None
    last_outcome: dict[str, Any] | None = None


def new_checkpoint_id(run_id: str) -> str:
    return f"cp:{run_id}:{uuid4().hex[:12]}"


def build_checkpoint(
    *,
    run_id: str,
    user_id: str,
    state: CognitiveState,
    pause_reason: Literal["system_interrupt", "user_pause"],
    checkpoint_id: str | None = None,
    resume_cursor: ResumeCursor = "select",
    pending_action: CognitiveAction | None = None,
    last_outcome: dict[str, Any] | None = None,
    original_message: str | None = None,
) -> CognitiveCheckpoint:
    message = (original_message or state.event.message or "").strip() or "(empty)"
    return CognitiveCheckpoint(
        checkpoint_id=checkpoint_id or new_checkpoint_id(run_id),
        run_id=run_id,
        user_id=str(user_id),
        pause_reason=pause_reason,
        original_message=message,
        resume_cursor=resume_cursor,
        state=state,
        pending_action=pending_action,
        last_outcome=last_outcome,
    )


def embed_checkpoint(run_state: dict[str, Any], checkpoint: CognitiveCheckpoint) -> dict[str, Any]:
    """把 checkpoint 写入 Run State 投影（经既有 Run State 持久化）。"""
    updated = dict(run_state)
    updated["checkpoint_id"] = checkpoint.checkpoint_id
    updated["cognitive_checkpoint"] = checkpoint.model_dump(mode="json")
    return updated


def extract_checkpoint(run_state: dict[str, Any] | None) -> CognitiveCheckpoint | None:
    if not isinstance(run_state, dict):
        return None
    payload = run_state.get("cognitive_checkpoint")
    if not isinstance(payload, dict):
        return None
    try:
        return CognitiveCheckpoint.model_validate(payload)
    except Exception:  # noqa: BLE001
        return None
