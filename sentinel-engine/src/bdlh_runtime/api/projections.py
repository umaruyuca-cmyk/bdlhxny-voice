"""API 投影与执行观察辅助（重构方案 D1/P3：自 routes.py 迁出）。

只做「内部执行结果 → API 响应结构」的纯投影，不含路由与编排。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bdlh_runtime.cognitive.contracts import PublicResponse
from bdlh_runtime.infra.context import RunContext
from bdlh_runtime.infra.recovery import graph_config
from bdlh_runtime.infra.runtime_path import COGNITIVE_RUNTIME_PATH, CognitiveExecutionProgress

from .schemas import RunResponse

logger = logging.getLogger("bdlh_runtime.api.projections")


class CognitiveExecutionObserverAdapter:
    """把 Cognitive 执行观察映射到进度标记（原 routes._CognitiveExecutionObserver）。"""

    def __init__(self, progress: CognitiveExecutionProgress) -> None:
        self._progress = progress

    def on_domain_request(self, request: Any) -> None:
        del request
        self._progress.domain_request_started = True
        logger.info("cognitive domain_request started")

    def on_domain_outcome(self, outcome: Any) -> None:
        del outcome
        logger.info("cognitive domain_outcome received")


def cognitive_state(
    run_id: str,
    session_id: str,
    response: PublicResponse,
    user_id: str | None = None,
    *,
    checkpoint_id: str | None = None,
    cognitive_checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把 Cognitive 公开响应投影为运行状态快照（RunStateReader 存储结构）。"""

    waiting = response.response_kind == "ASK_USER"
    paused = "PAUSED_BY_USER" in response.audit_codes
    failed = response.response_kind in {"BLOCKED", "CAPABILITY_NOT_ENABLED"}
    status = "PAUSED_BY_USER" if paused else ("WAITING_USER" if waiting else ("FAILED" if failed else "SUCCESS"))
    payload = {
        "run_id": run_id,
        "thread_id": session_id,
        "user_id": user_id,
        "runtime_path": COGNITIVE_RUNTIME_PATH,
        "status": status,
        "next_stage": "paused" if paused else ("awaiting_user" if waiting else "completed"),
        "final_response": response.model_dump(mode="json"),
        "events": [
            {
                "schema_version": "1.0",
                "event_type": "response.completed",
                "run_id": run_id,
                "runtime_path": COGNITIVE_RUNTIME_PATH,
                "status": status if status != "SUCCESS" else "COMPLETED",
                "audit_codes": response.audit_codes,
            }
        ],
        "checkpoint_id": checkpoint_id,
    }
    if cognitive_checkpoint is not None:
        payload["cognitive_checkpoint"] = cognitive_checkpoint
    return payload


def config_for(
    run_id: str,
    user_id: str | None = None,
    thread_id: str | None = None,
    checkpoint_id: str | None = None,
) -> dict[str, Any]:
    """构建统一恢复配置；thread_id 优先用传入值（多轮对话），否则等于 run_id。"""

    tid = thread_id or run_id
    config = graph_config(RunContext(thread_id=tid, run_id=run_id, user_id=user_id))
    if checkpoint_id is not None:
        config["configurable"]["checkpoint_id"] = checkpoint_id
    return config


def public_state(run_id: str, state: dict[str, Any]) -> RunResponse:
    """将内部 State 投影为 API 响应，避免泄露完整输入和工具原始数据。"""

    waiting = bool(state.get("__interrupt__"))
    return RunResponse(
        run_id=run_id,
        thread_id=state.get("thread_id"),
        status="WAITING_USER" if waiting else state.get("status", "RUNNING"),
        next_stage=state.get("next_stage"),
        final_response=state.get("final_response"),
        interrupts=state.get("__interrupt__", []),
        events=state.get("events", []),
    )


def chat_final_payload(response: PublicResponse) -> dict[str, Any]:
    """把 PublicResponse 的可解释性字段投影为 SSE ``response.final`` 终帧。

    ``token`` 事件保持纯文本；本函数只承载证据链、数据时间、审计码、限制与披露。
    ``disclosures`` 对应契约字段 ``risk_disclosures``。
    """

    return {
        "schema_version": "1.0",
        "type": "response.final",
        "response_kind": response.response_kind,
        "response_structure": response.response_structure,
        "evidence_refs": list(response.evidence_refs),
        "data_times": list(response.data_times),
        "audit_codes": list(response.audit_codes),
        "limitations": list(response.limitations),
        "disclosures": list(response.risk_disclosures),
    }


def chat_answer_text(final_response: Any) -> str:
    """把 Cognitive 结构化响应投影成聊天页正文。"""

    if final_response is None:
        return ""
    if isinstance(final_response, str):
        return final_response.strip()
    if isinstance(final_response, dict):
        for key in ("answer", "summary", "message", "text"):
            value = final_response.get(key)
            if isinstance(value, str) and value.strip():
                limitations = final_response.get("limitations")
                if isinstance(limitations, list) and limitations:
                    notes = "\n".join(f"- {item}" for item in limitations if str(item).strip())
                    return f"{value.strip()}\n\n限制说明：\n{notes}" if notes else value.strip()
                return value.strip()
        return json.dumps(final_response, ensure_ascii=False, default=str)
    return str(final_response).strip()
