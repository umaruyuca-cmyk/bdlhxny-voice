"""记忆节点测试：用户确认后的知识入库（Phase 4）。"""

from __future__ import annotations

import pytest

from bdlh_runtime.runtimes.langgraph.nodes.nodes import (
    make_persist_memory_node,
)


class RecordingMemoryStore:
    """记录 add 调用的测试用 MemoryStore。"""

    def __init__(self):
        self.added: list[tuple[str, str, dict]] = []  # (content, user_id, metadata)

    async def search(self, query, user_id, *, limit=5):
        return []

    async def get_profile(self, user_id):
        return None

    async def add(self, content, user_id, *, metadata=None):
        self.added.append((content, user_id, metadata or {}))


def _state_with_result(confirmation=None):
    """构造包含分析结果的状态。"""
    return {
        "user_id": "u1",
        "run_id": "run-1",
        "request": {"message": "分析 600519"},
        "understand": {"entities": {"instruments": ["600519"]}},
        "analysis_result": {
            "conclusions": [
                {"text": "技术面偏多", "confidence": "MEDIUM"},
            ]
        },
        "confirmation": confirmation,
    }


@pytest.mark.asyncio
async def test_confirmed_knowledge_saved():
    """用户确认后，结论以 knowledge_type=confirmed 写入记忆。"""
    store = RecordingMemoryStore()
    node = make_persist_memory_node(store)
    await node(_state_with_result(confirmation={"confirmed": True}))
    # v2.1 §9.2：不写常规摘要，只写已确认知识 → 1 次 add
    assert len(store.added) == 1
    knowledge_adds = [a for a in store.added if a[2].get("knowledge_type") == "confirmed"]
    assert len(knowledge_adds) == 1
    assert "已确认结论" in knowledge_adds[0][0]
    assert knowledge_adds[0][2]["symbol"] == "600519"


@pytest.mark.asyncio
async def test_rejected_confirmation_not_saved_as_knowledge():
    """用户拒绝时，不写入已确认知识（只保留常规沉淀）。"""
    store = RecordingMemoryStore()
    node = make_persist_memory_node(store)
    await node(_state_with_result(confirmation={"confirmed": False}))
    knowledge_adds = [a for a in store.added if a[2].get("knowledge_type") == "confirmed"]
    assert knowledge_adds == []


@pytest.mark.asyncio
async def test_no_confirmation_not_persisted():
    """v2.1 §9.2：无用户确认时不自动写记忆（不写临时摘要）。"""
    store = RecordingMemoryStore()
    node = make_persist_memory_node(store)
    await node(_state_with_result(confirmation=None))
    assert len(store.added) == 0  # 无确认不写任何记忆
