"""聊天会话目录端口。

运行时会话由 Java Data Plane 管理；本模块仅保留无外部依赖的测试替身。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol
from uuid import uuid4

from .errors import ConfigurationError


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class ChatSession:
    session_id: str
    user_id: str | None
    title: str = "新的对话"
    messages: list[ChatMessage] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    pending_run_id: str | None = None
    pending_thread_id: str | None = None
    pending_checkpoint_id: str | None = None
    pending_runtime_path: str | None = None
    pause_reason: str | None = None  # system_interrupt | user_pause | null
    awaiting_route_confirm: bool = False
    verified_entity_state: dict | None = None


class ChatSessionStore(Protocol):
    def ensure(self, requested_id: str | None, user_id: str | None) -> ChatSession: ...

    def list_for_user(self, user_id: str | None, limit: int) -> list[ChatSession]: ...

    def get(self, session_id: str, user_id: str | None) -> ChatSession | None: ...

    def add_message(self, session_id: str, user_id: str | None, role: str, content: str) -> None: ...

    def prepare_regeneration(self, session_id: str, user_id: str | None) -> None: ...

    def set_pending(
        self,
        session_id: str,
        user_id: str | None,
        *,
        run_id: str | None,
        thread_id: str | None,
        checkpoint_id: str | None,
        runtime_path: str | None = None,
        pause_reason: str | None = None,
        awaiting_route_confirm: bool = False,
    ) -> None: ...

    def get_verified_entity_state(self, session_id: str, user_id: str | None) -> dict | None: ...

    def set_verified_entity_state(
        self, session_id: str, user_id: str | None, state: dict | None
    ) -> None: ...

    def delete(self, session_id: str, user_id: str | None) -> bool: ...


class InMemoryChatSessionStore:
    """测试专用实现；所有键都包含可信 user_id。"""

    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], ChatSession] = {}
        self._lock = RLock()

    @staticmethod
    def _user_key(user_id: str | None) -> str:
        return str(user_id) if user_id is not None else "__anonymous__"

    def _key(self, session_id: str, user_id: str | None) -> tuple[str, str]:
        return self._user_key(user_id), session_id

    def ensure(self, requested_id: str | None, user_id: str | None) -> ChatSession:
        normalized = str(requested_id or "").strip()
        with self._lock:
            if normalized:
                existing = self._sessions.get(self._key(normalized, user_id))
                if existing is not None:
                    return existing
                session_id = normalized
            else:
                session_id = str(uuid4())
            session = ChatSession(session_id=session_id, user_id=user_id)
            self._sessions[self._key(session_id, user_id)] = session
            return session

    def list_for_user(self, user_id: str | None, limit: int) -> list[ChatSession]:
        user_key = self._user_key(user_id)
        with self._lock:
            sessions = [session for (owner, _), session in self._sessions.items() if owner == user_key]
            return sorted(sessions, key=lambda item: item.updated_at, reverse=True)[: max(1, limit)]

    def get(self, session_id: str, user_id: str | None) -> ChatSession | None:
        with self._lock:
            return self._sessions.get(self._key(session_id, user_id))

    def add_message(self, session_id: str, user_id: str | None, role: str, content: str) -> None:
        normalized = str(content or "").strip()
        if not normalized:
            return
        with self._lock:
            session = self._sessions.get(self._key(session_id, user_id))
            if session is None:
                raise KeyError(f"chat session not found: {session_id}")
            session.messages.append(ChatMessage(role=role, content=normalized))
            if role == "user" and session.title == "新的对话":
                session.title = normalized[:24] + ("…" if len(normalized) > 24 else "")
            session.updated_at = datetime.now(UTC)

    def prepare_regeneration(self, session_id: str, user_id: str | None) -> None:
        with self._lock:
            session = self._sessions.get(self._key(session_id, user_id))
            if session is None:
                raise KeyError(f"chat session not found: {session_id}")
            if session.messages and session.messages[-1].role == "assistant":
                session.messages.pop()
            session.updated_at = datetime.now(UTC)

    def set_pending(
        self,
        session_id: str,
        user_id: str | None,
        *,
        run_id: str | None,
        thread_id: str | None,
        checkpoint_id: str | None,
        runtime_path: str | None = None,
        pause_reason: str | None = None,
        awaiting_route_confirm: bool = False,
    ) -> None:
        with self._lock:
            session = self._sessions.get(self._key(session_id, user_id))
            if session is None:
                raise KeyError(f"chat session not found: {session_id}")
            session.pending_run_id = run_id
            session.pending_thread_id = thread_id
            session.pending_checkpoint_id = checkpoint_id
            session.pending_runtime_path = runtime_path
            if run_id is None:
                session.pause_reason = None
                session.awaiting_route_confirm = False
            else:
                session.pause_reason = pause_reason
                session.awaiting_route_confirm = bool(awaiting_route_confirm)
            session.updated_at = datetime.now(UTC)

    def get_verified_entity_state(self, session_id: str, user_id: str | None) -> dict | None:
        with self._lock:
            session = self._sessions.get(self._key(session_id, user_id))
            if session is None:
                return None
            state = session.verified_entity_state
            return dict(state) if isinstance(state, dict) else None

    def set_verified_entity_state(
        self, session_id: str, user_id: str | None, state: dict | None
    ) -> None:
        with self._lock:
            session = self._sessions.get(self._key(session_id, user_id))
            if session is None:
                raise KeyError(f"chat session not found: {session_id}")
            session.verified_entity_state = dict(state) if isinstance(state, dict) else None
            session.updated_at = datetime.now(UTC)

    def delete(self, session_id: str, user_id: str | None) -> bool:
        with self._lock:
            return self._sessions.pop(self._key(session_id, user_id), None) is not None


def create_chat_session_store(*, environment: str = "test") -> ChatSessionStore:
    """创建测试用内存会话目录；运行时数据必须经 Java Data Plane。"""

    if environment != "test":
        raise ConfigurationError("Python 内存聊天会话目录仅允许测试环境")
    return InMemoryChatSessionStore()


class ChatSessionVerifiedEntityPersistence:
    """把受控实体快照落到 Chat Session（内存或 Java Data Plane）。"""

    def __init__(self, store: ChatSessionStore) -> None:
        self._store = store

    def load(self, *, user_id: str, session_id: str) -> dict | None:
        return self._store.get_verified_entity_state(session_id, user_id)

    def save(self, *, user_id: str, session_id: str, state: dict | None) -> None:
        self._store.set_verified_entity_state(session_id, user_id, state)
