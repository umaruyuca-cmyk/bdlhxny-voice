"""面向聊天页面的轻量会话目录。

会话正文的流程状态仍由 LangGraph Checkpointer 保存；本目录只提供前端需要的
会话列表、消息快照和等待恢复的运行位置。开发环境使用内存实现，生产环境后续
可替换为数据库实现而不改变 HTTP 或 Graph 契约。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    pending_run_id: str | None = None
    pending_thread_id: str | None = None
    pending_checkpoint_id: str | None = None


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
    ) -> None: ...

    def delete(self, session_id: str, user_id: str | None) -> bool: ...


class InMemoryChatSessionStore:
    """线程安全的开发实现，所有键都包含可信 user_id。"""

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
            # 客户端临时 ID 不作为服务端正式会话 ID，避免跨设备/并发碰撞。
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
            session.updated_at = datetime.now(timezone.utc)

    def prepare_regeneration(self, session_id: str, user_id: str | None) -> None:
        """移除目录快照中的最后一条回答，保留原用户问题。"""

        with self._lock:
            session = self._sessions.get(self._key(session_id, user_id))
            if session is None:
                raise KeyError(f"chat session not found: {session_id}")
            if session.messages and session.messages[-1].role == "assistant":
                session.messages.pop()
            session.updated_at = datetime.now(timezone.utc)

    def set_pending(
        self,
        session_id: str,
        user_id: str | None,
        *,
        run_id: str | None,
        thread_id: str | None,
        checkpoint_id: str | None,
    ) -> None:
        with self._lock:
            session = self._sessions.get(self._key(session_id, user_id))
            if session is None:
                raise KeyError(f"chat session not found: {session_id}")
            session.pending_run_id = run_id
            session.pending_thread_id = thread_id
            session.pending_checkpoint_id = checkpoint_id
            session.updated_at = datetime.now(timezone.utc)

    def delete(self, session_id: str, user_id: str | None) -> bool:
        with self._lock:
            return self._sessions.pop(self._key(session_id, user_id), None) is not None


class PostgresChatSessionStore:
    """生产会话目录；正文与待恢复 checkpoint 定位均持久化到 PostgreSQL。"""

    def __init__(self, dsn: str):
        try:
            import psycopg  # noqa: F401
        except ImportError as exc:
            raise ConfigurationError(
                "PostgreSQL 聊天会话存储需要安装 psycopg[binary]"
            ) from exc
        self._dsn = dsn
        self._setup()

    @staticmethod
    def _user_key(user_id: str | None) -> str:
        return str(user_id) if user_id is not None else "__anonymous__"

    def _connect(self):
        import psycopg

        return psycopg.connect(self._dsn)

    def _setup(self) -> None:
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS bdlh_runtime_chat_session (
                    user_id VARCHAR(64) NOT NULL,
                    session_id VARCHAR(64) NOT NULL,
                    title VARCHAR(255) NOT NULL DEFAULT '新的对话',
                    pending_run_id VARCHAR(64),
                    pending_thread_id VARCHAR(255),
                    pending_checkpoint_id VARCHAR(255),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, session_id)
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS bdlh_runtime_chat_message (
                    id BIGSERIAL PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    session_id VARCHAR(64) NOT NULL,
                    role VARCHAR(16) NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id, session_id)
                        REFERENCES bdlh_runtime_chat_session(user_id, session_id)
                        ON DELETE CASCADE
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_bdlh_runtime_chat_message_session
                ON bdlh_runtime_chat_message(user_id, session_id, id)
            """)

    def _session_from_row(self, connection, row) -> ChatSession:
        messages = connection.execute(
            """
            SELECT role, content FROM bdlh_runtime_chat_message
            WHERE user_id = %s AND session_id = %s ORDER BY id
            """,
            (row[0], row[1]),
        ).fetchall()
        return ChatSession(
            user_id=row[0] if row[0] != "__anonymous__" else None,
            session_id=row[1],
            title=row[2],
            pending_run_id=row[3],
            pending_thread_id=row[4],
            pending_checkpoint_id=row[5],
            updated_at=row[6],
            messages=[ChatMessage(role=item[0], content=item[1]) for item in messages],
        )

    def ensure(self, requested_id: str | None, user_id: str | None) -> ChatSession:
        owner = self._user_key(user_id)
        normalized = str(requested_id or "").strip()
        if normalized:
            existing = self.get(normalized, user_id)
            if existing is not None:
                return existing
        session_id = str(uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO bdlh_runtime_chat_session(user_id, session_id)
                VALUES (%s, %s)
                """,
                (owner, session_id),
            )
        session = self.get(session_id, user_id)
        if session is None:
            raise RuntimeError("聊天会话创建后无法读取")
        return session

    def list_for_user(self, user_id: str | None, limit: int) -> list[ChatSession]:
        owner = self._user_key(user_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT user_id, session_id, title, pending_run_id,
                       pending_thread_id, pending_checkpoint_id, updated_at
                FROM bdlh_runtime_chat_session
                WHERE user_id = %s
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (owner, max(1, limit)),
            ).fetchall()
            return [self._session_from_row(connection, row) for row in rows]

    def get(self, session_id: str, user_id: str | None) -> ChatSession | None:
        owner = self._user_key(user_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT user_id, session_id, title, pending_run_id,
                       pending_thread_id, pending_checkpoint_id, updated_at
                FROM bdlh_runtime_chat_session
                WHERE user_id = %s AND session_id = %s
                """,
                (owner, session_id),
            ).fetchone()
            return self._session_from_row(connection, row) if row else None

    def add_message(self, session_id: str, user_id: str | None, role: str, content: str) -> None:
        owner = self._user_key(user_id)
        normalized = str(content or "").strip()
        if not normalized:
            return
        with self._connect() as connection:
            row = connection.execute(
                "SELECT title FROM bdlh_runtime_chat_session WHERE user_id = %s AND session_id = %s",
                (owner, session_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"chat session not found: {session_id}")
            connection.execute(
                """
                INSERT INTO bdlh_runtime_chat_message(user_id, session_id, role, content)
                VALUES (%s, %s, %s, %s)
                """,
                (owner, session_id, role, normalized),
            )
            title = row[0]
            if role == "user" and title == "新的对话":
                title = normalized[:24] + ("…" if len(normalized) > 24 else "")
            connection.execute(
                """
                UPDATE bdlh_runtime_chat_session SET title = %s, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s AND session_id = %s
                """,
                (title, owner, session_id),
            )

    def prepare_regeneration(self, session_id: str, user_id: str | None) -> None:
        owner = self._user_key(user_id)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM bdlh_runtime_chat_session WHERE user_id = %s AND session_id = %s",
                (owner, session_id),
            ).fetchone()
            if existing is None:
                raise KeyError(f"chat session not found: {session_id}")
            connection.execute(
                """
                DELETE FROM bdlh_runtime_chat_message
                WHERE id = (
                    SELECT id FROM bdlh_runtime_chat_message
                    WHERE user_id = %s AND session_id = %s
                    ORDER BY id DESC LIMIT 1
                ) AND role = 'assistant'
                """,
                (owner, session_id),
            )
            connection.execute(
                """
                UPDATE bdlh_runtime_chat_session SET updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s AND session_id = %s
                """,
                (owner, session_id),
            )

    def set_pending(
        self,
        session_id: str,
        user_id: str | None,
        *,
        run_id: str | None,
        thread_id: str | None,
        checkpoint_id: str | None,
    ) -> None:
        owner = self._user_key(user_id)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE bdlh_runtime_chat_session
                SET pending_run_id = %s, pending_thread_id = %s,
                    pending_checkpoint_id = %s, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s AND session_id = %s
                """,
                (run_id, thread_id, checkpoint_id, owner, session_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"chat session not found: {session_id}")

    def delete(self, session_id: str, user_id: str | None) -> bool:
        owner = self._user_key(user_id)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM bdlh_runtime_chat_session WHERE user_id = %s AND session_id = %s",
                (owner, session_id),
            )
            return cursor.rowcount > 0


def create_chat_session_store(
    *,
    environment: str = "development",
    postgres_dsn: str | None = None,
) -> ChatSessionStore:
    if environment == "production":
        if not postgres_dsn:
            raise ConfigurationError("生产聊天会话目录需要 POSTGRES_DSN")
        return PostgresChatSessionStore(postgres_dsn)
    return InMemoryChatSessionStore()
