"""RunStateReader 端口与 InMemory 实现的契约测试（重构方案 D1/P2a）。"""

from __future__ import annotations

from bdlh_runtime.config import Settings
from bdlh_runtime.infra.application import AgentRuntimeApplication
from bdlh_runtime.infra.run_state import InMemoryRunStateReader, RunStateReader


def test_inmemory_put_load_roundtrip():
    reader = InMemoryRunStateReader()
    reader.save("run-1", "7", {"status": "RUNNING", "events": []})
    assert reader.load("run-1", "7") == {"status": "RUNNING", "events": [], "user_id": "7"}


def test_inmemory_load_missing_returns_none():
    reader = InMemoryRunStateReader()
    assert reader.load("no-such-run", "7") is None


def test_inmemory_overwrite_keeps_last_state():
    reader = InMemoryRunStateReader()
    reader.save("run-1", "7", {"status": "RUNNING"})
    reader.save("run-1", "7", {"status": "SUCCESS"})
    assert reader.load("run-1", "7") == {"status": "SUCCESS", "user_id": "7"}


def test_inmemory_satisfies_reader_protocol():
    reader = InMemoryRunStateReader()
    assert isinstance(reader, RunStateReader)


def test_application_provides_run_state_reader_by_default():
    app = AgentRuntimeApplication(settings=Settings(environment="development"))
    assert isinstance(app.run_state_reader, InMemoryRunStateReader)
    # 两个应用实例不共享内存快照
    other = AgentRuntimeApplication(settings=Settings(environment="development"))
    app.run_state_reader.save("run-1", "7", {"status": "RUNNING"})
    assert other.run_state_reader.load("run-1", "7") is None


def test_inmemory_reader_rejects_another_users_run():
    reader = InMemoryRunStateReader()
    reader.save("run-1", "7", {"status": "RUNNING"})

    assert reader.load("run-1", "8") is None
