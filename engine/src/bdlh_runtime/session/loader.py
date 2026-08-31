"""冻结完整 Session 用例的加载与校验。

session 文件是交叉验证的唯一原始输入;gold 文件**绝不**进入本模块——
编译链路(loader/serializer/compiler)在任何情况下都不得读取 gold,
否则实验发生答案泄漏(见 docs/context/Session交叉验证设计.md)。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ALLOWED_EVENT_TYPES = frozenset({"user_message", "assistant_message", "tool_call", "tool_result"})


class SessionValidationError(ValueError):
    """Session 文件结构不合法(顺序、配对、缺失字段等)。"""


def canonical_json_hash(payload: Any) -> str:
    """稳定 hash:键排序 + 紧凑分隔 + ensure_ascii=False,再取 sha256。"""

    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True)
class SessionEvent:
    seq: int
    event_id: str
    occurred_at: str
    type: str
    content: str
    role: str
    call_id: str | None = None
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    status: str | None = None
    error_code: str | None = None
    #: 可选来源引用:指向同一实体前序事件的 event_id(或外部 source);
    #: 缺省 None → 序列化时以自身 event_id 兜底(与既有口径一致)
    source_id: str | None = None

    @property
    def is_tool_pair_member(self) -> bool:
        return self.type in {"tool_call", "tool_result"}


@dataclass(frozen=True)
class SessionCase:
    session_id: str
    session_version: int
    title: str
    owner_id: str | None
    fixture_set_id: str | None
    tool_catalog_version: str | None
    current_question: str
    visible_tools: tuple[str, ...]
    context_target_tokens: int
    events: tuple[SessionEvent, ...]
    source_hash: str
    source_path: str

    @property
    def event_ids(self) -> tuple[str, ...]:
        return tuple(event.event_id for event in self.events)


def load_session(path: str | Path) -> SessionCase:
    """读取并校验一份冻结 Session;任何结构问题直接抛错,不做修复。"""

    file_path = Path(path)
    raw = json.loads(file_path.read_text(encoding="utf-8"))
    for field in ("session_id", "session_version", "events", "runtime_case"):
        if field not in raw:
            raise SessionValidationError(f"session 文件缺少字段 {field}: {file_path}")
    runtime = raw["runtime_case"]
    question = str(runtime.get("current_question") or "").strip()
    if not question:
        raise SessionValidationError("runtime_case.current_question 不能为空")

    events_raw = raw["events"]
    if not events_raw:
        raise SessionValidationError("events 不能为空")

    events: list[SessionEvent] = []
    open_calls: dict[str, SessionEvent] = {}
    pair_of_result: dict[str, str] = {}  # result event_id -> call event_id
    previous_seq = 0
    seen_ids: set[str] = set()
    for row in events_raw:
        seq = int(row.get("seq") or 0)
        event_id = str(row.get("event_id") or "")
        event_type = str(row.get("type") or "")
        if seq != previous_seq + 1:
            raise SessionValidationError(f"事件 seq 必须从 1 连续递增: got {seq} after {previous_seq}")
        if not event_id or event_id in seen_ids:
            raise SessionValidationError(f"event_id 缺失或重复: {event_id!r}")
        if event_type not in _ALLOWED_EVENT_TYPES:
            raise SessionValidationError(f"未知事件类型 {event_type!r} ({event_id})")
        content = str(row.get("content") or "")
        if event_type in {"user_message", "assistant_message"} and not content.strip():
            raise SessionValidationError(f"{event_id} 正文为空")
        seen_ids.add(event_id)
        previous_seq = seq
        events.append(
            SessionEvent(
                seq=seq,
                event_id=event_id,
                occurred_at=str(row.get("occurred_at") or ""),
                type=event_type,
                content=content,
                role=str(row.get("role") or ""),
                call_id=(str(row["call_id"]) if row.get("call_id") else None),
                tool_name=(str(row["tool_name"]) if row.get("tool_name") else None),
                arguments=(dict(row["arguments"]) if isinstance(row.get("arguments"), dict) else None),
                status=(str(row["status"]) if row.get("status") else None),
                error_code=(str(row["error_code"]) if row.get("error_code") else None),
                source_id=(str(row["source_id"]) if row.get("source_id") else None),
            )
        )
        if event_type == "tool_call":
            if not events[-1].call_id or not events[-1].tool_name:
                raise SessionValidationError(f"tool_call 事件 {event_id} 缺少 call_id/tool_name")
            open_calls[events[-1].call_id] = events[-1]
        elif event_type == "tool_result":
            call_id = events[-1].call_id
            if not call_id or call_id not in open_calls:
                raise SessionValidationError(f"tool_result 事件 {event_id} 没有配对的 tool_call")
            pair_of_result[event_id] = open_calls.pop(call_id).event_id
    if open_calls:
        dangling = ", ".join(sorted(open_calls))
        raise SessionValidationError(f"存在没有结果的 tool_call: {dangling}")

    # result 事件必须紧跟其 call 事件(保持原文里调用与结果相邻)
    for event in events:
        if event.type == "tool_result":
            call_id = pair_of_result.get(event.event_id)
            if call_id is None:
                continue
            call_event = next(item for item in events if item.event_id == call_id)
            if event.seq != call_event.seq + 1:
                raise SessionValidationError(f"tool_result {event.event_id} 未紧跟其 tool_call {call_id}")

    return SessionCase(
        session_id=str(raw["session_id"]),
        session_version=int(raw.get("session_version") or 1),
        title=str(raw.get("title") or raw["session_id"]),
        owner_id=(str(raw["owner_id"]) if raw.get("owner_id") else None),
        fixture_set_id=(str(raw.get("fixture_set_id")) if raw.get("fixture_set_id") else None),
        tool_catalog_version=(str(raw["tool_catalog_version"]) if raw.get("tool_catalog_version") else None),
        current_question=question,
        visible_tools=tuple(str(item) for item in runtime.get("visible_tools") or ()),
        context_target_tokens=int(runtime.get("context_target_tokens") or 0),
        events=tuple(events),
        source_hash=canonical_json_hash(raw),
        source_path=str(file_path),
    )


def load_variants(path: str | Path) -> dict[str, Any]:
    """读取变体配置(只供运行控制器/编译器使用,不是模型输入)。"""

    return json.loads(Path(path).read_text(encoding="utf-8"))
