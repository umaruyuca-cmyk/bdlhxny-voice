"""上下文会话双读来源接口。"""

from __future__ import annotations

import os
from typing import Protocol

from bdlh_runtime.data_client import DataClient, DataServiceError
from bdlh_runtime.experiments import compression
from bdlh_runtime.session.loader import SessionCase, SessionEvent, canonical_json_hash


class SessionSource(Protocol):
    """固定文件与生产数据库必须共同实现的最小读取契约。"""

    source_type: str

    def list_sessions(self) -> list[dict]: ...

    def get_session(self, session_id: str) -> tuple[SessionCase, dict]: ...


class FrozenSessionSource:
    """三个冻结长 Session 的只读来源；不执行自动入库。"""

    source_type = "FROZEN_FILE"

    def list_sessions(self) -> list[dict]:
        return [dict(row, source_type=self.source_type) for row in compression.public_session_overview()]

    def get_session(self, session_id: str) -> tuple[SessionCase, dict]:
        session, variants, _path = compression._load_session_bundle(session_id)
        return session, variants


class DatabaseSessionSource:
    """从 Data Service 读取生产会话；不直接连接 PostgreSQL。"""

    source_type = "PRODUCTION_DB"

    def __init__(self, owner_id: str, client: DataClient | None = None) -> None:
        if not owner_id:
            raise ValueError("owner_id is required for database context sessions")
        self.owner_id = owner_id
        self.client = client or DataClient()

    def list_sessions(self) -> list[dict]:
        return [self._session_summary(row) for row in self.client.list_context_sessions(self.owner_id)]

    def get_session(self, session_id: str) -> tuple[SessionCase, dict]:
        payload = self.client.get_context_session(self.owner_id, session_id)
        events = tuple(self._event(row) for row in payload.get("events") or [])
        if not events:
            raise DataServiceError(f"production context session {session_id!r} has no events")
        current = next((event for event in reversed(events) if event.type == "user_message"), None)
        if current is None:
            raise DataServiceError(f"production context session {session_id!r} has no user request")
        target_tokens = max(1024, int(os.getenv("CONTEXT_TARGET_TOKENS", "8192")))
        source_hash = str(_get(payload, "sourceHash", "source_hash") or "")
        if not source_hash:
            source_hash = canonical_json_hash(
                {"session_id": session_id, "event_ids": [event.event_id for event in events]}
            )
        session = SessionCase(
            session_id=str(_get(payload, "sessionId", "session_id") or session_id),
            session_version=int(_get(payload, "sourceVersion", "source_version") or 1),
            title=str(payload.get("title") or session_id),
            owner_id=self.owner_id,
            fixture_set_id=None,
            tool_catalog_version=None,
            current_question=current.content,
            visible_tools=(),
            context_target_tokens=target_tokens,
            events=events,
            source_hash=source_hash,
            source_path=f"data-service://context/sessions/{session_id}",
        )
        variants = {
            "context_variants": [
                {
                    "variant_id": "budgeted-hybrid-v1",
                    "strategy": "budgeted",
                    "strategy_version": "budgeted-hybrid-v1",
                    "token_budget": target_tokens,
                    "reserved_tokens": {
                        "recent_session_events": min(2048, target_tokens // 4),
                        "history_summary_max": min(2560, target_tokens // 3),
                    },
                }
            ]
        }
        return session, variants

    def _session_summary(self, row: dict) -> dict:
        return {
            "session_id": str(_get(row, "sessionId", "session_id") or ""),
            "title": str(row.get("title") or ""),
            "source_type": str(_get(row, "sourceType", "source_type") or self.source_type),
            "source_hash": str(_get(row, "sourceHash", "source_hash") or ""),
            "source_version": int(_get(row, "sourceVersion", "source_version") or 1),
            "event_count": int(_get(row, "eventCount", "event_count") or 0),
            "turn_count": int(_get(row, "turnCount", "turn_count") or 0),
            "user_message_count": int(_get(row, "userMessageCount", "user_message_count") or 0),
            "default_current_request_event_id": _get(
                row,
                "defaultCurrentRequestEventId",
                "default_current_request_event_id",
            ),
            "status": str(row.get("status") or "ACTIVE"),
            "updated_at": _get(row, "updatedAt", "updated_at"),
        }

    @staticmethod
    def _event(row: dict) -> SessionEvent:
        event_type = str(_get(row, "eventType", "event_type") or "")
        if event_type not in {"user_message", "assistant_message", "tool_call", "tool_result"}:
            raise DataServiceError(f"unsupported production session event type {event_type!r}")
        content = str(row.get("content") or "")
        if not content:
            content_ref = str(_get(row, "contentRef", "content_ref") or "")
            content = f"[reference:{content_ref}]" if content_ref else "[empty event]"
        return SessionEvent(
            seq=int(_get(row, "sequence", "seq") or 0),
            event_id=str(_get(row, "eventId", "event_id") or ""),
            occurred_at=str(_get(row, "occurredAt", "occurred_at") or ""),
            type=event_type,
            content=content,
            role=str(row.get("role") or ""),
            call_id=_optional(row, "toolCallId", "tool_call_id"),
            source_id=_optional(row, "parentEventId", "parent_event_id"),
        )


class ShadowSessionSource:
    """生产来源优先、冻结来源兜底的双读模式；不双写、不自动迁移。"""

    source_type = "SHADOW_READ"

    def __init__(self, primary: SessionSource, fallback: SessionSource | None = None) -> None:
        self.primary = primary
        self.fallback = fallback or FrozenSessionSource()

    def list_sessions(self) -> list[dict]:
        try:
            primary_rows = self.primary.list_sessions()
        except DataServiceError:
            primary_rows = []
        by_id = {str(row.get("session_id")): row for row in self.fallback.list_sessions()}
        for row in primary_rows:
            by_id[str(row.get("session_id"))] = row
        return list(by_id.values())

    def get_session(self, session_id: str) -> tuple[SessionCase, dict]:
        try:
            return self.primary.get_session(session_id)
        except DataServiceError:
            return self.fallback.get_session(session_id)


def source_for_mode(owner_id: str, mode: str | None = None, client: DataClient | None = None) -> SessionSource:
    """构造运行模式来源；未知模式拒绝启动，避免静默切换数据口径。"""

    selected = (mode or os.getenv("CONTEXT_MEMORY_MODE", "legacy")).strip().lower()
    if selected == "legacy":
        return FrozenSessionSource()
    database = DatabaseSessionSource(owner_id, client=client)
    if selected == "incremental":
        return database
    if selected == "shadow":
        return ShadowSessionSource(database)
    raise ValueError(f"unsupported CONTEXT_MEMORY_MODE {selected!r}")


def _get(row: dict, *keys: str):
    for key in keys:
        if key in row:
            return row[key]
    return None


def _optional(row: dict, *keys: str) -> str | None:
    value = _get(row, *keys)
    return str(value) if value not in (None, "") else None
