"""G7：MemoryWriter 过滤与 Remote 召回 degraded。"""

from __future__ import annotations

import pytest

from tests.helpers_memory import StubMemoryStore

from bdlh_runtime.memory.recall import recall_semantic_memory
from bdlh_runtime.memory.remote import RemoteMemoryStore
from bdlh_runtime.memory.writer import MemoryWriter


@pytest.mark.asyncio
async def test_writer_rejects_l4_metadata() -> None:
    writer = MemoryWriter(StubMemoryStore())
    result = await writer.persist(
        user_id="7",
        content="我偏好简洁回答",
        metadata={"knowledge_type": "confirmed", "risk_tolerance": "BALANCED"},
    )
    assert result.attempted is False
    assert result.enqueued is False
    assert result.skipped_reason == "filtered_or_unconfirmed"


@pytest.mark.asyncio
async def test_writer_rejects_unconfirmed() -> None:
    writer = MemoryWriter(StubMemoryStore())
    result = await writer.persist(
        user_id="7",
        content="我偏好简洁回答",
        metadata={"knowledge_type": "inferred"},
    )
    assert result.enqueued is False


@pytest.mark.asyncio
async def test_writer_accepts_confirmed_soft_preference_on_remote_enqueue() -> None:
    calls: list[dict] = []

    class FakeClient:
        def call(self, method, path, user_id, *, payload=None, query=None, allow_not_found=False):
            calls.append({"method": method, "path": path, "user_id": user_id, "payload": payload})
            return {"eventId": payload["candidateId"]}

    store = RemoteMemoryStore(
        base_url="http://memory.test",
        internal_token="token",
        java_client=FakeClient(),  # type: ignore[arg-type]
    )
    writer = MemoryWriter(store)
    result = await writer.persist(
        user_id="7",
        content="确认记住：我偏好先看结论再看证据",
        metadata={"knowledge_type": "confirmed", "run_id": "run-1"},
    )
    assert result.enqueued is True
    assert result.degraded is False
    assert calls and calls[0]["path"] == "/internal/v1/memory-candidates"
    assert "risk_tolerance" not in calls[0]["payload"]["metadata"]


@pytest.mark.asyncio
async def test_remote_search_marks_degraded_on_failure() -> None:
    class UnusedJava:
        def call(self, *args, **kwargs):
            raise AssertionError("search must not call Java")

    store = RemoteMemoryStore(
        base_url="http://127.0.0.1:1",
        internal_token="token",
        java_client=UnusedJava(),  # type: ignore[arg-type]
    )
    recall = await recall_semantic_memory(store, user_id="7", query="茅台")
    assert recall.records == []
    assert recall.degraded is True
    assert recall.limitation == "semantic_memory_degraded"


@pytest.mark.asyncio
async def test_stub_recall_is_not_degraded() -> None:
    recall = await recall_semantic_memory(StubMemoryStore(), user_id="7", query="茅台")
    assert recall.records == []
    assert recall.degraded is False
