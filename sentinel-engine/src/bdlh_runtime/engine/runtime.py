"""EngineRuntime：把 AgentLoop 接到既有 InputEvent / PublicResponse 契约。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from bdlh_runtime.engine.checkpoint import CognitiveCheckpoint, build_checkpoint
from bdlh_runtime.engine.contracts import (
    CognitiveActionSummary,
    CognitiveActionType,
    CognitiveExecution,
    CognitiveState,
    InputEvent,
    InputEventType,
    PublicResponse,
)
from bdlh_runtime.engine.loop import AgentLoop, AgentResult, AgentTurn

_GUEST_IDS = frozenset({"", "guest", "anonymous"})


class EngineRuntime:
    """chat / agent_runs / 唤醒共用的 ``.run(InputEvent)`` 适配器。"""

    def __init__(
        self,
        loop: AgentLoop,
        *,
        pause_check: Callable[[str], bool] | None = None,
        executor: Any = None,
        catalog: Any = None,
    ) -> None:
        self._loop = loop
        self._pause_check = pause_check
        self._executor = executor
        self.catalog = catalog

    async def run(
        self,
        event: InputEvent,
        *,
        observer: Any = None,
        checkpoint: CognitiveCheckpoint | None = None,
    ) -> CognitiveExecution:
        run_id = event.run_id or event.event_id
        if self._pause_check is not None and self._pause_check(run_id):
            return _paused_execution(event)
        history: list[dict[str, str]] = []
        message = event.message
        if checkpoint is not None:
            original = (checkpoint.original_message or "").strip()
            if original and original != message:
                history = [
                    {"role": "user", "content": original},
                    {"role": "assistant", "content": "请补充刚才缺的信息。"},
                ]
        if self._executor is not None:
            if hasattr(self._executor, "set_user"):
                self._executor.set_user(event.user_id)
            if hasattr(self._executor, "set_observer"):
                self._executor.set_observer(observer)
        try:
            result = await self._loop.run(
                AgentTurn(
                    user_id=event.user_id,
                    message=message,
                    scene_tag=_scene_tag(event),
                    authenticated=event.user_id not in _GUEST_IDS,
                    history=history,
                    run_id=run_id,
                ),
                stream=observer if observer is not None and hasattr(observer, "on_token") else None,
            )
        finally:
            if self._executor is not None and hasattr(self._executor, "set_observer"):
                self._executor.set_observer(None)
        return _execution_from_result(event, result)


def _scene_tag(event: InputEvent) -> str:
    if event.event_type == InputEventType.SCHEDULED_WAKEUP:
        return "watch"
    return "research"


def _paused_execution(event: InputEvent) -> CognitiveExecution:
    state = CognitiveState(event=event, public_events=["run.paused"], error_codes=["PAUSED_BY_USER"])
    response = PublicResponse(
        response_kind="ASK_USER",
        response_structure="CLARIFICATION",
        message="已按你的操作暂停。回复「继续」可接着刚才的分析，或直接提出新的问题。",
        audit_codes=["PAUSED_BY_USER"],
    )
    checkpoint = build_checkpoint(
        run_id=event.run_id or event.event_id,
        user_id=event.user_id,
        state=state,
        pause_reason="user_pause",
        original_message=event.message,
    )
    return CognitiveExecution(state=state, response=response, checkpoint=checkpoint)


def _execution_from_result(event: InputEvent, result: AgentResult) -> CognitiveExecution:
    kind = "ANSWER"
    structure = "KNOWLEDGE"
    audits = [item.audit_code for item in result.audits if item.audit_code]
    if result.fastpath_name == "forbidden":
        kind = "BLOCKED"
        structure = "SAFETY_BLOCK"
        audits = ["SEMANTIC_FORBIDDEN"]
    elif result.fastpath_name == "chitchat":
        audits = ["SEMANTIC_CHITCHAT"]
    elif result.fastpath_name == "knowledge":
        audits = ["SEMANTIC_KNOWLEDGE"]
    elif result.degraded:
        kind = "LIMITED"
        audits = ["LLM_UNAVAILABLE"]
    blocked = any(item.status == "REJECTED" and item.audit_code for item in result.audits)
    if blocked and not result.fastpath_name:
        kind = "BLOCKED"
        structure = "SAFETY_BLOCK"
        audits = [item.audit_code or "GUARDRAIL_BLOCKED" for item in result.audits if item.status == "REJECTED"]
    answer = (result.answer or "").strip()
    if not answer:
        answer = "当前对话能力暂不可用，请稍后重试。" if result.degraded or kind == "LIMITED" else "已完成。"
    public_events: list[str] = []
    if kind == "BLOCKED":
        public_events.append("guardrail.blocked")
    history = [
        CognitiveActionSummary(
            action_type=CognitiveActionType.RESPOND,
            reason_code=audits[0] if audits else "RESPOND",
        )
    ]
    state = CognitiveState(
        event=event,
        public_events=public_events,
        action_history=history,
        requested_tool_calls=len(result.audits),
    )
    response = PublicResponse(
        response_kind=kind,  # type: ignore[arg-type]
        response_structure=structure,  # type: ignore[arg-type]
        message=answer,
        audit_codes=audits,
    )
    return CognitiveExecution(
        state=state,
        response=response,
        checkpoint=None,
        observations=_dump_observations(result.observations),
        tool_trace=_dump_tool_trace(result.audits),
        entered_loop=result.entered_loop,
        fastpath_name=result.fastpath_name,
        loaded_tools=list(result.loaded_tools),
    )


def _dump_observations(items: list[Any]) -> list[dict[str, Any]]:
    dumped: list[dict[str, Any]] = []
    for item in items:
        if hasattr(item, "model_dump"):
            dumped.append(item.model_dump(mode="json"))
        elif isinstance(item, dict):
            dumped.append(dict(item))
    return dumped


def _dump_tool_trace(audits: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "tool": item.tool_name,
            "argumentsSummary": item.arguments_summary,
            "status": item.status,
            "elapsedMs": item.elapsed_ms,
            "auditCode": item.audit_code,
        }
        for item in audits
    ]
