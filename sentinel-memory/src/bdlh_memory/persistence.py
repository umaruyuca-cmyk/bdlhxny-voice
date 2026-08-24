from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID
from uuid import uuid4


class InboxRepository(Protocol):
    def claim(self, event_id: UUID) -> bool: ...
    def complete(self, event_id: UUID, summary: str) -> None: ...
    def fail(self, event_id: UUID, summary: str) -> None: ...
    def audit_deletion(self, user_id: str, summary: str) -> None: ...


class InMemoryInboxRepository:
    def __init__(self) -> None:
        self.events: set[UUID] = set()
        self.deletions: list[tuple[str, str]] = []

    def claim(self, event_id: UUID) -> bool:
        if event_id in self.events:
            return False
        self.events.add(event_id)
        return True

    def complete(self, event_id: UUID, summary: str) -> None:
        del event_id, summary

    def fail(self, event_id: UUID, summary: str) -> None:
        self.events.discard(event_id)

    def audit_deletion(self, user_id: str, summary: str) -> None:
        self.deletions.append((user_id, summary))


class PostgresInboxRepository:
    """Memory Service only accesses its own ``memory`` schema."""

    GROUP = "bdlh-memory-consumer"

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    def _connect(self):
        return self._pool.connection()

    def claim(self, event_id: UUID) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "INSERT INTO memory.consumer_inbox(consumer_group, event_id, status) VALUES (%s, %s, 'PROCESSING') "
                "ON CONFLICT (consumer_group, event_id) DO UPDATE SET status = 'PROCESSING', "
                "updated_at = CURRENT_TIMESTAMP WHERE memory.consumer_inbox.status = 'FAILED' "
                "OR memory.consumer_inbox.updated_at <= CURRENT_TIMESTAMP - INTERVAL '5 minutes' RETURNING event_id",
                (self.GROUP, event_id),
            ).fetchone()
            return row is not None

    def complete(self, event_id: UUID, summary: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE memory.consumer_inbox SET status = 'PROCESSED', result_summary = %s, "
                "processed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
                "WHERE consumer_group = %s AND event_id = %s",
                (summary[:1000], self.GROUP, event_id),
            )

    def fail(self, event_id: UUID, summary: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE memory.consumer_inbox SET status = 'FAILED', last_error = %s, "
                "updated_at = CURRENT_TIMESTAMP WHERE consumer_group = %s AND event_id = %s",
                (summary[:1000], self.GROUP, event_id),
            )

    def audit_deletion(self, user_id: str, summary: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO memory.deletion_audit(audit_id, user_id, summary) VALUES (%s, %s, %s)",
                (uuid4(), user_id, summary[:1000]),
            )
