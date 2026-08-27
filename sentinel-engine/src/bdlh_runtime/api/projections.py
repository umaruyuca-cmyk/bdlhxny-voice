"""API 投影与执行观察辅助（重构方案 D1/P3：自 routes.py 迁出）。

只做「内部执行结果 → API 响应结构」的纯投影，不含路由与编排。
"""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Sequence
from typing import Any

from bdlh_runtime.engine.contracts import PublicResponse
from bdlh_runtime.infra.context import RunContext
from bdlh_runtime.infra.recovery import graph_config
from bdlh_runtime.infra.runtime_path import COGNITIVE_RUNTIME_PATH, CognitiveExecutionProgress

from .schemas import SUITABILITY_DISCLOSURE, ChatResultV2, ResultBlock, RunResponse

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


def chat_final_payload(
    response: PublicResponse,
    *,
    observations: Sequence[Any] | None = None,
    tool_trace: Sequence[dict[str, Any]] | None = None,
    entered_loop: bool | None = None,
    fastpath_name: str | None = None,
    loaded_tools: Sequence[str] | None = None,
) -> dict[str, Any]:
    """把公开回复投影为 SSE ``response.final``（ChatResult v2）。

    ``answer`` 来自模型解读文本；``blocks`` 由 Observation 的 ``result_type`` +
    ``payload`` 直接投影，数字不经 LLM 转述。``disclosures`` 对应契约字段
    ``risk_disclosures``。为兼容既有终帧断言，保留 ``response_kind`` 等附加字段。
    循环元数据（``entered_loop`` / ``fastpath_name`` / ``loaded_tools``）供回路页
    按 LangChain 消息链外显，不进入 ChatResult v2 模型字段。
    """

    result = ChatResultV2(
        answer=response.message,
        blocks=project_blocks(observations or ()),
        tool_trace=[dict(item) for item in (tool_trace or ())],
        evidence_refs=list(response.evidence_refs),
        audit_codes=list(response.audit_codes),
        disclosures=list(response.risk_disclosures),
    )
    payload = result.model_dump(mode="json")
    payload.update(
        {
            "schema_version": "1.0",
            "type": "response.final",
            "response_kind": response.response_kind,
            "response_structure": response.response_structure,
            "data_times": list(response.data_times),
            "limitations": list(response.limitations),
            "entered_loop": bool(entered_loop),
            "fastpath_name": fastpath_name,
            "loaded_tools": list(loaded_tools or ()),
        }
    )
    return payload


_KNOWN_BLOCK_TYPES: frozenset[str] = frozenset(
    {"ScoreCard", "AnalysisReport", "SuitabilityDraft", "PortfolioHealth", "QuoteTable"}
)
_SUITABILITY_CONCLUSION_KEYS = frozenset(
    {
        "conclusion",
        "verdict",
        "suitable",
        "suitability",
        "suitability_verdict",
        "recommendation",
        "recommend",
        "结论",
        "适合",
        "推荐买入",
        "建议买入",
    }
)


def project_blocks(observations: Sequence[Any]) -> list[ResultBlock]:
    """把工具 Observation 的类型化结果直接投影为 ResultBlock（不改数字）。"""

    blocks: list[ResultBlock] = []
    for item in observations:
        result_type, payload = _typed_result(item)
        if result_type not in _KNOWN_BLOCK_TYPES or payload is None:
            continue
        projected = copy.deepcopy(payload)
        if result_type == "SuitabilityDraft":
            projected = _project_suitability_payload(projected)
        observation_id, source, data_time = _observation_trace(item)
        blocks.append(
            ResultBlock(
                type=result_type,  # type: ignore[arg-type]
                payload=projected,
                observation_id=observation_id,
                source=source,
                data_time=data_time,
            )
        )
    return blocks


def _typed_result(item: Any) -> tuple[str | None, dict[str, Any] | None]:
    result_type = _attr_or_key(item, "result_type")
    payload = _attr_or_key(item, "payload")
    data = _attr_or_key(item, "data")
    if not result_type and isinstance(data, dict):
        result_type = data.get("result_type")
        if not isinstance(payload, dict):
            payload = data.get("payload")
    if isinstance(result_type, str):
        result_type = result_type.strip() or None
    if not isinstance(payload, dict):
        payload = None
    return result_type, payload


def _project_suitability_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """C-2：匹配项与风险项成组、固定披露、去掉结论位；其余字段原样保留。"""

    matches = copy.deepcopy(payload.get("matches") or [])
    risks = copy.deepcopy(payload.get("risks") or [])
    projected = {key: value for key, value in payload.items() if key not in _SUITABILITY_CONCLUSION_KEYS}
    projected["matches"] = matches
    projected["risks"] = risks
    projected["disclosure"] = SUITABILITY_DISCLOSURE
    return projected


def _observation_trace(item: Any) -> tuple[str | None, str | None, str | None]:
    observation_id = _attr_or_key(item, "observation_id")
    provenance = _attr_or_key(item, "provenance") or []
    source = None
    data_time = None
    if provenance:
        first = provenance[0]
        source = _attr_or_key(first, "source")
        data_time = _attr_or_key(first, "retrieved_at") or _attr_or_key(first, "as_of")
    return (
        str(observation_id) if observation_id else None,
        str(source) if source else None,
        str(data_time) if data_time else None,
    )


def _attr_or_key(item: Any, name: str) -> Any:
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


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
