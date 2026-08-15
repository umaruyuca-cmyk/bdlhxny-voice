"""分析历史存储测试（v2.1 §9.3）。

覆盖：存储 save/get/list_by_thread、权限隔离（仅本人可查）、
make_persist_history_node 节点把运行快照写入历史。
"""

from __future__ import annotations

import pytest

from bdlh_runtime.contracts.history import AnalysisHistoryRecord
from bdlh_runtime.runtime.history import InMemoryAnalysisHistoryStore, create_history_store
from bdlh_runtime.runtimes.langgraph.nodes.nodes import make_persist_history_node


def _record(**overrides) -> AnalysisHistoryRecord:
    base = {
        "history_id": "h1",
        "thread_id": "t1",
        "run_id": "r1",
        "authenticated_user_id": "u1",
        "request_snapshot": {"message": "分析 600519"},
        "status": "SUCCESS",
    }
    base.update(overrides)
    return AnalysisHistoryRecord(**base)


def test_save_and_get():
    store = InMemoryAnalysisHistoryStore()
    rec = _record()
    store.save(rec)
    assert store.get("h1") is rec
    assert store.get("nope") is None


def test_list_by_thread_permission_isolation():
    """权限隔离（v2.1 P0-6）：仅本人可查，他人/匿名返回空。"""
    store = InMemoryAnalysisHistoryStore()
    store.save(_record(history_id="h1", authenticated_user_id="u1"))
    store.save(_record(history_id="h2", authenticated_user_id="u2"))
    # u1 只看到自己的
    assert [r.history_id for r in store.list_by_thread("t1", "u1")] == ["h1"]
    # u2 只看到自己的
    assert [r.history_id for r in store.list_by_thread("t1", "u2")] == ["h2"]
    # 无 user_id 返回空
    assert store.list_by_thread("t1", None) == []


def test_create_history_store_returns_in_memory():
    store = create_history_store()
    assert isinstance(store, InMemoryAnalysisHistoryStore)


@pytest.mark.asyncio
async def test_persist_history_node_writes_record():
    """make_persist_history_node 把运行快照写入历史存储。"""
    store = InMemoryAnalysisHistoryStore()
    node = make_persist_history_node(store)
    state = {
        "run_id": "r1",
        "thread_id": "t1",
        "user_id": "u1",
        "request": {"message": "分析 600519"},
        "intent": {"symbol": "600519", "analysis_type": "technical"},
        "observations": [{"capability": "market.get_realtime_quote", "status": "SUCCESS"}],
        "analysis_result": {"status": "SUCCESS", "conclusions": []},
        "status": "SUCCESS",
    }
    result = await node(state)
    assert any(e["event_type"] == "history.saved" for e in result["events"])
    records = store.list_by_thread("t1", "u1")
    assert len(records) == 1
    assert records[0].run_id == "r1"
    assert records[0].authenticated_user_id == "u1"
    assert records[0].status == "SUCCESS"
    assert records[0].intent_snapshot["symbol"] == "600519"


@pytest.mark.asyncio
async def test_persist_history_node_failure_non_blocking():
    """历史写入失败不阻塞主流程（仅记事件）。"""
    class FailingStore:
        def save(self, record):
            raise RuntimeError("db down")

    node = make_persist_history_node(FailingStore())
    result = await node({"run_id": "r1", "thread_id": "t1"})
    assert any(e["event_type"] == "history.save_failed" for e in result["events"])
