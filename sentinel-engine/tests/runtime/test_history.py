"""分析历史存储测试（v2.1 §9.3）。

覆盖：存储 save/get/list_by_thread、权限隔离（仅本人可查）。
"""

from __future__ import annotations

import pytest

from bdlh_runtime.contracts.history import AnalysisHistoryRecord
from bdlh_runtime.runtime.history import InMemoryAnalysisHistoryStore, create_history_store


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


def test_create_history_store_always_refuses():
    from bdlh_runtime.runtime.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="Java Data Plane"):
        create_history_store()
    with pytest.raises(ConfigurationError, match="Java Data Plane"):
        create_history_store(environment="test")
    with pytest.raises(ConfigurationError, match="Java Data Plane"):
        create_history_store(environment="production")
