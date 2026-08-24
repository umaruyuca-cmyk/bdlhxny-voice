from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from bdlh_memory.config import Settings
from bdlh_memory.domain import MemoryCandidate, SearchRequest
from bdlh_memory.main import create_app
from bdlh_memory.persistence import InMemoryInboxRepository
from bdlh_memory.service import MemoryApplication


class FakeGateway:
    def __init__(self) -> None:
        self.added: list[tuple[str, str, dict]] = []

    async def search(self, user_id: str, query: str, top_k: int):
        del user_id, query, top_k
        return []

    async def add(self, user_id: str, content: str, metadata: dict) -> None:
        self.added.append((user_id, content, metadata))

    async def get(self, memory_id: str):
        del memory_id
        return None

    async def delete(self, memory_id: str) -> None:
        del memory_id

    async def delete_user(self, user_id: str) -> None:
        del user_id


@pytest.mark.asyncio
async def test_candidate_is_idempotent_and_requires_confirmed_knowledge() -> None:
    gateway = FakeGateway()
    app = MemoryApplication(gateway, InMemoryInboxRepository())
    candidate = MemoryCandidate(
        event_id=uuid4(), authenticated_user_id="7", content="用户确认长期偏好价值投资",
        metadata={"knowledge_type": "confirmed", "run_id": "run-1"},
    )

    assert await app.consume(candidate) is True
    assert await app.consume(candidate) is False
    assert len(gateway.added) == 1


@pytest.mark.asyncio
async def test_unconfirmed_candidate_is_not_persisted() -> None:
    gateway = FakeGateway()
    app = MemoryApplication(gateway, InMemoryInboxRepository())
    candidate = MemoryCandidate(
        event_id=uuid4(), authenticated_user_id="7", content="未确认推断",
        metadata={"knowledge_type": "inferred"},
    )

    assert await app.consume(candidate) is False
    assert gateway.added == []


def test_memory_http_api_requires_matching_authenticated_user_scope() -> None:
    app = create_app(
        Settings(internal_token="service-token"),
        MemoryApplication(FakeGateway(), InMemoryInboxRepository()),
    )
    client = TestClient(app)
    payload = {"user_id": "user-7", "query": "confirmed preference", "top_k": 3}

    missing_scope = client.post(
        "/internal/v1/memories/search",
        headers={"X-Internal-Token": "service-token"},
        json=payload,
    )
    mismatched_scope = client.post(
        "/internal/v1/memories/search",
        headers={"X-Internal-Token": "service-token", "X-Authenticated-User-Id": "user-8"},
        json=payload,
    )
    accepted = client.post(
        "/internal/v1/memories/search",
        headers={"X-Internal-Token": "service-token", "X-Authenticated-User-Id": "user-7"},
        json=payload,
    )

    assert missing_scope.status_code == 401
    assert mismatched_scope.status_code == 403
    assert accepted.status_code == 200
