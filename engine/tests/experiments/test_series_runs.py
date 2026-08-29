"""实验组单次运行链路测试(P0-7 13.4/13.5):Fake LLM / 替身执行器,不访问真实模型。

覆盖:创建实验组不运行 Agent、一次 POST 只创建一个 Run、幂等重放与 409、
单活跃运行约束、repeat_index 自动分配、失败不自动续跑、统计快照对接。
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from bdlh_runtime.experiments.series_store import SeriesConflictError, SeriesStore


class FakeChatModel:
    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self._index = 0

    def bind_tools(self, tools, **_kwargs):
        return self

    async def ainvoke(self, messages, **_kwargs):
        assert self._index < len(self._responses), "FakeChatModel 响应已耗尽"
        item = self._responses[self._index]
        self._index += 1
        return item

    async def astream(self, messages, **kwargs):
        yield await self.ainvoke(messages, **kwargs)


def _call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def _case() -> Any:
    from bdlh_runtime.experiments.comparison import ComparisonCase
    from bdlh_runtime.experiments.judge import CallRelationSpec

    return ComparisonCase(
        case_id="cmp-series-01",
        case_version=1,
        title="实验组用例",
        message="上海今天天气如何?",
        scene="general",
        allowed_tools=("weather.get_forecast",),
        default_visible_tools=("weather.get_forecast",),
        fixture_set_id="fixture-v1",
        call_relation=CallRelationSpec(),
        conditions={
            "mock_fixtures": [
                {
                    "tool": "weather.get_forecast",
                    "match_mode": "subset",
                    "match_arguments": {"location": "上海"},
                    "status": "success",
                    "result": {"forecast": "多云 25℃"},
                    "fixture_id": "fx-w",
                    "fixture_version": 1,
                }
            ]
        },
    )


class _MemoryRepo:
    def __init__(self, cases):
        self._cases = cases

    def get_public_case(self, case_id):
        return next((case for case in self._cases if case.case_id == case_id), None)


@pytest.fixture()
def owner_client():
    from fastapi.testclient import TestClient

    from bdlh_runtime import run_api

    client = TestClient(run_api.app)
    client.app.dependency_overrides[run_api.require_login] = lambda: {"username": "owner"}
    yield client
    client.app.dependency_overrides.clear()


@pytest.fixture()
def series_env(tmp_path, monkeypatch, owner_client):
    """独立 series 目录 + 记忆用例仓库 + 假 data 客户端;返回 (client, store, run_api)。"""
    import bdlh_runtime.run_api as run_api
    from bdlh_runtime.experiments import public_case_repository

    store = SeriesStore(root=tmp_path / "series")
    monkeypatch.setattr(run_api, "_SERIES_STORE", store)
    monkeypatch.setattr(run_api, "_data", lambda: _FakeDataClient())
    monkeypatch.setattr(public_case_repository, "get_case_repository", lambda: _MemoryRepo([_case()]))
    return owner_client, store, run_api


def _wait_for_run(client: Any, series_id: str, run_key: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = client.get(f"/api/v1/experiment-series/{series_id}/runs").json()["runs"]
        row = next((r for r in rows if r["run_key"] == run_key), None)
        if row and row["status"] in ("done", "failed"):
            return row
        time.sleep(0.05)
    raise AssertionError(f"运行 {run_key} 未在 {timeout}s 内结束")


def _fake_payload(variant: str, repeat: int) -> dict[str, Any]:
    return {
        "run_id": f"fake-{variant}-{repeat}",
        "variant_label": variant,
        "repeat_index": repeat - 1,
        "config_hash": "cfg-fake",
        "governance_profile": "standard",
        "answer": "上海今天多云,25℃。",
        "tool_calls": [],
        "audits": [],
        "stop_reason": "COMPLETED",
        "actual_agent_steps": 2,
        "duration_ms": 500,
        "validity": "VALID",
        "error": None,
    }


def test_create_series_only_saves_definition(series_env):
    client, _store, _run_api = series_env
    response = client.post(
        "/api/v1/experiment-series",
        json={"template_id": "governance-on-off", "case_id": "cmp-series-01"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["variant_labels"] == ["off", "standard"]
    assert payload["definition_hash"]
    detail = client.get(f"/api/v1/experiment-series/{payload['series_id']}").json()
    assert detail["total_runs"] == 0
    assert detail["counts_by_variant"] == {"off": 0, "standard": 0}
    assert detail["active_run"] is None


def test_create_series_rejects_unknown_case_and_template(series_env):
    client, _store, _run_api = series_env
    unknown_case = client.post(
        "/api/v1/experiment-series",
        json={"template_id": "governance-on-off", "case_id": "no-such-case"},
    )
    assert unknown_case.status_code == 400
    unknown_template = client.post(
        "/api/v1/experiment-series",
        json={"template_id": "no-such-template", "case_id": "cmp-series-01"},
    )
    assert unknown_template.status_code == 400


def test_single_run_creates_exactly_one_run(series_env, monkeypatch):
    client, store, run_api = series_env
    created = client.post(
        "/api/v1/experiment-series",
        json={"template_id": "governance-on-off", "case_id": "cmp-series-01"},
    ).json()
    series_id = created["series_id"]

    monkeypatch.setattr(
        run_api,
        "execute_prepared_series_run",
        lambda prepared, **kwargs: _fake_payload(prepared.planned.variant_label, 1),
    )
    response = client.post(
        f"/api/v1/experiment-series/{series_id}/runs",
        json={"variant_id": "off", "idempotency_key": "key-run-0001"},
    )
    assert response.status_code == 200
    assert response.json()["run_key"] == "run-001"
    row = _wait_for_run(client, series_id, "run-001")
    assert row["status"] == "done"
    assert row["result"]["variant_label"] == "off"
    # 阶段二:运行启动即回写 agent_runs 行标识(实时订阅键)
    assert row.get("agent_run_id")

    detail = client.get(f"/api/v1/experiment-series/{series_id}").json()
    assert detail["total_runs"] == 1
    assert detail["counts_by_variant"] == {"off": 1, "standard": 0}


def test_idempotency_replay_and_conflict(series_env, monkeypatch):
    client, _store, run_api = series_env
    series_id = client.post(
        "/api/v1/experiment-series",
        json={"template_id": "governance-on-off", "case_id": "cmp-series-01"},
    ).json()["series_id"]
    monkeypatch.setattr(
        run_api,
        "execute_prepared_series_run",
        lambda prepared, **kwargs: _fake_payload(prepared.planned.variant_label, 1),
    )
    first = client.post(
        f"/api/v1/experiment-series/{series_id}/runs",
        json={"variant_id": "off", "idempotency_key": "key-run-0002"},
    ).json()
    _wait_for_run(client, series_id, first["run_key"])
    replay = client.post(
        f"/api/v1/experiment-series/{series_id}/runs",
        json={"variant_id": "off", "idempotency_key": "key-run-0002"},
    ).json()
    assert replay["run_key"] == first["run_key"]  # 同键重放返回原运行

    conflict = client.post(
        f"/api/v1/experiment-series/{series_id}/runs",
        json={"variant_id": "standard", "idempotency_key": "key-run-0002"},
    )
    assert conflict.status_code == 409  # 同键不同变体:明确冲突,不静默复用


def test_single_active_run_constraint_and_repeat_allocation(series_env, monkeypatch):
    client, _store, run_api = series_env
    series_id = client.post(
        "/api/v1/experiment-series",
        json={"template_id": "governance-on-off", "case_id": "cmp-series-01"},
    ).json()["series_id"]

    release = __import__("threading").Event()

    def blocking_executor(prepared, **kwargs):
        release.wait(timeout=10)
        return _fake_payload(variant_id, 1)

    monkeypatch.setattr(run_api, "execute_prepared_series_run", blocking_executor)
    first = client.post(
        f"/api/v1/experiment-series/{series_id}/runs",
        json={"variant_id": "off"},
    ).json()
    second = client.post(
        f"/api/v1/experiment-series/{series_id}/runs",
        json={"variant_id": "standard"},
    )
    assert second.status_code == 409  # 单活跃运行约束
    release.set()
    _wait_for_run(client, series_id, first["run_key"])

    monkeypatch.setattr(
        run_api, "execute_prepared_series_run", lambda prepared, **kwargs: _fake_payload("off", 2)
    )
    third = client.post(
        f"/api/v1/experiment-series/{series_id}/runs",
        json={"variant_id": "off"},
    ).json()
    assert third["repeat_index"] == 2  # 自动分配第 2 次,不重跑第 1 次
    assert third["run_key"] != first["run_key"]
    _wait_for_run(client, series_id, third["run_key"])


def test_failed_run_does_not_auto_start_next(series_env, monkeypatch):
    client, _store, run_api = series_env
    series_id = client.post(
        "/api/v1/experiment-series",
        json={"template_id": "governance-on-off", "case_id": "cmp-series-01"},
    ).json()["series_id"]

    def broken_executor(prepared, **kwargs):
        raise RuntimeError("模拟执行失败")

    monkeypatch.setattr(run_api, "execute_prepared_series_run", broken_executor)
    response = client.post(
        f"/api/v1/experiment-series/{series_id}/runs",
        json={"variant_id": "off", "idempotency_key": "key-fail-0001"},
    ).json()
    row = _wait_for_run(client, series_id, response["run_key"])
    assert row["status"] == "failed"
    assert "模拟执行失败" in row["error"]
    # 失败后没有第二个运行被自动启动;同键重试返回原失败条目
    replay = client.post(
        f"/api/v1/experiment-series/{series_id}/runs",
        json={"variant_id": "off", "idempotency_key": "key-fail-0001"},
    )
    assert replay.status_code == 200
    assert replay.json()["run_key"] == response["run_key"]


def test_series_statistics_endpoint(series_env, monkeypatch):
    client, _store, run_api = series_env
    series_id = client.post(
        "/api/v1/experiment-series",
        json={"template_id": "governance-on-off", "case_id": "cmp-series-01"},
    ).json()["series_id"]

    monkeypatch.setattr(
        run_api,
        "execute_prepared_series_run",
        lambda prepared, **kwargs: _fake_payload(prepared.planned.variant_label, 1),
    )
    first = client.post(
        f"/api/v1/experiment-series/{series_id}/runs",
        json={"variant_id": "off"},
    ).json()
    _wait_for_run(client, series_id, first["run_key"])

    def broken_executor(prepared, **kwargs):
        raise RuntimeError("LLM_UNAVAILABLE: 模拟鉴权失败")

    monkeypatch.setattr(run_api, "execute_prepared_series_run", broken_executor)
    failed = client.post(
        f"/api/v1/experiment-series/{series_id}/runs",
        json={"variant_id": "standard"},
    ).json()
    _wait_for_run(client, series_id, failed["run_key"])

    snapshot = client.get(f"/api/v1/statistics/experiment-series/{series_id}").json()
    assert snapshot["template_id"] == "governance-on-off"
    assert snapshot["included_run_ids"] == ["fake-off-1"]
    assert snapshot["by_variant"]["off"]["sample_level"]["level"] == "single-observation"
    assert snapshot["by_variant"]["standard"]["sample_level"]["level"] == "no-data"
    excluded_reasons = {row["run_id"]: row["reason"] for row in snapshot["excluded_runs"]}
    assert excluded_reasons[failed["run_key"]] == "LLM_UNAVAILABLE"


def test_execute_series_run_with_fake_llm(series_env, monkeypatch):
    """执行器直连测试:复用模板执行链路,产出统计模块可消费的运行 payload。"""
    from bdlh_runtime.experiments.series_runner import execute_series_run
    from bdlh_runtime.experiments.series_store import SeriesRecord

    record = SeriesRecord(
        series_id="series-direct",
        template_id="governance-on-off",
        template_version=1,
        case_id="cmp-series-01",
        title="直连",
        variant_labels=["off", "standard"],
        fixed_conditions={},
        fixed_conditions_hash="sha256:x",
    )
    payload = execute_series_run(
        record,
        "off",
        model="fake-model",
        llm=FakeChatModel(
            [
                _call("weather.get_forecast", {"location": "上海"}, "c1"),
                AIMessage(content="上海今天多云,25℃。"),
            ]
        ),
    )
    assert payload["variant_label"] == "off"
    assert payload["config_hash"]
    assert payload["actual_agent_steps"] >= 1
    assert payload["validity"] == "VALID"


# ── 压缩方法对照迁移实验组(13.13 收尾) ─────────────────────────────────────

COMPRESSION_SESSION = "ctx-session-context-engine-debug-01"
SESSION_ID = COMPRESSION_SESSION  # 与 test_compression.py 同一最小 Session(26 事件)


class _FakeLLMSummarizer:
    def summarize(self, texts, max_tokens, counter):  # noqa: ANN001
        return "【LLM摘要】" + " ".join(text[:32] for text in texts)


def test_unknown_compression_session_rejected(series_env):
    client, _store, _run_api = series_env
    response = client.post(
        "/api/v1/experiment-series",
        json={"template_id": "compression-method-comparison", "session_id": "no-such-session"},
    )
    assert response.status_code == 400
    assert "未知压缩 Session" in response.json()["detail"]


def test_compression_series_flow_via_api(series_env, monkeypatch):
    """压缩对照走实验组:创建(Session)→ 逐方法单样本 → 统计含 success_rate。"""
    client, _store, run_api = series_env
    created = client.post(
        "/api/v1/experiment-series",
        json={"template_id": "compression-method-comparison", "session_id": COMPRESSION_SESSION},
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["variant_labels"] == ["budgeted", "budgeted-llm"]
    assert payload["case_id"] == COMPRESSION_SESSION

    def stub_executor(series, variant_id, **kwargs):
        row = _fake_payload(variant_id, 1)
        row["task_success"] = True
        row["judgment"] = {"tool_correct": True}
        return row

    monkeypatch.setattr(run_api, "execute_series_run", stub_executor)
    for variant in ("budgeted", "budgeted-llm"):
        entry = client.post(
            f"/api/v1/experiment-series/{payload['series_id']}/runs",
            json={"variant_id": variant},
        )
        assert entry.status_code == 200
        _wait_for_run(client, payload["series_id"], entry.json()["run_key"])
    snapshot = client.get(f"/api/v1/statistics/experiment-series/{payload['series_id']}").json()
    assert snapshot["by_variant"]["budgeted"]["success_rate"] == 1.0
    assert snapshot["by_variant"]["budgeted-llm"]["sample_level"]["level"] == "single-observation"


def test_run_single_compression_method_shape():
    """单变体压缩执行器:NativeRunRecord 同形 payload + run_id 逐次唯一。"""
    import asyncio

    from bdlh_runtime.experiments.compression import run_single_compression_method

    async def fake_runner(session, artifact, agent_mode_id, run_key, max_agent_steps, *, llm=None):
        return {
            "answer": "按最终决定执行。", "error": None, "tool_calls": [],
            "stop_reason": "FINAL_ANSWER", "actual_agent_steps": 1, "duration_ms": 5,
        }

    first = asyncio.run(
        run_single_compression_method(SESSION_ID, "budgeted", cell_runner=fake_runner, max_agent_steps=4)
    )
    second = asyncio.run(
        run_single_compression_method(SESSION_ID, "budgeted", cell_runner=fake_runner, max_agent_steps=4)
    )
    assert first["variant_label"] == "budgeted"
    assert first["config_hash"]
    assert first["validity"] == "VALID"
    assert first["actual_agent_steps"] == 1
    assert first["run_id"] != second["run_id"]  # 同变体多次重复不会被统计判重

    llm_variant = asyncio.run(
        run_single_compression_method(
            SESSION_ID, "budgeted-llm",
            cell_runner=fake_runner, max_agent_steps=4, llm_summarizer=_FakeLLMSummarizer(),
        )
    )
    assert llm_variant["variant_label"] == "budgeted-llm"
    assert llm_variant["config_hash"] != first["config_hash"]  # 摘要器不同 → 配置不同


# ── 数据库版实验组存储:状态文档存 run_batches.report,series_id=batch_id ──────


class _FakeDataClient:
    def __init__(self):
        self.batches: dict[str, dict] = {}
        self.reports: dict[str, dict] = {}
        self.runs: dict[str, dict] = {}
        self._seq = 0

    def create_batch(self, *, name, experiment_type, fixed_conditions):
        self._seq += 1
        batch_id = f"batch-{self._seq:03d}"
        self.batches[batch_id] = {
            "name": name, "experiment_type": experiment_type, "fixed_conditions": fixed_conditions,
        }
        return batch_id

    def save_batch_report(self, batch_id, report):
        self.reports[batch_id] = report

    def get_batch_report(self, batch_id):
        return self.reports.get(batch_id)

    def create_run(self, payload):
        self._seq += 1
        run_id = f"run-{self._seq:03d}"
        self.runs[run_id] = {"status": "CREATED", **payload}
        return run_id

    def update_model_config(self, run_id, model_config):
        self.runs[run_id]["model_config"] = model_config

    def save_events(self, run_id, events):
        self.runs.setdefault(run_id, {}).setdefault("events", []).extend(events)

    def complete_run(self, run_id, output, *, status, error_category=None):
        self.runs[run_id]["status"] = status
        self.runs[run_id]["output"] = output


def _series_record() -> "SeriesRecord":
    from bdlh_runtime.experiments.series_store import SeriesRecord

    return SeriesRecord(
        series_id="provisional",
        template_id="governance-on-off",
        template_version=1,
        case_id="cmp-x",
        title="t",
        variant_labels=["off", "standard"],
        fixed_conditions={},
        fixed_conditions_hash="sha256:x",
    )


def test_db_series_store_uses_batch_id_and_persists_state():
    from bdlh_runtime.experiments.series_store import DbSeriesStore

    data = _FakeDataClient()
    store = DbSeriesStore(lambda: data)
    stored = store.create(_series_record())
    assert stored.series_id == "batch-001"  # series_id 以数据服务生成的 batch_id 为准
    assert data.batches["batch-001"]["experiment_type"] == "series:governance-on-off"

    entry, replayed = store.begin_run(
        stored.series_id, variant_id="off", idempotency_key="k1", request_hash="h1"
    )
    assert not replayed and entry["run_key"] == "run-001"
    again, replayed2 = store.begin_run(
        stored.series_id, variant_id="off", idempotency_key="k1", request_hash="h1"
    )
    assert replayed2 and again["run_key"] == "run-001"  # 幂等重放

    with pytest.raises(SeriesConflictError):
        store.begin_run(stored.series_id, variant_id="standard", idempotency_key=None, request_hash="h2")

    store.complete_run(stored.series_id, "run-001", {"run_id": "r1", "answer": "ok"})
    record = store.get(stored.series_id)
    assert record.runs[0]["status"] == "done"
    assert record.counts_by_variant() == {"off": 1, "standard": 0}

    # 全部状态在数据库报告列,无本地文件参与;数据服务不可达时 get 如实返回 None
    assert data.reports["batch-001"]["series_state_version"] == DbSeriesStore.STATE_VERSION
    empty = _FakeDataClient()
    empty.reports["legacy"] = {"runs": [1, 2]}  # 旧格式批次报告不是实验组状态文档
    assert DbSeriesStore(lambda: empty).get("legacy") is None
    assert DbSeriesStore(lambda: empty).get("no-such") is None


def test_db_series_store_cancel_removes_queued_entry():
    from bdlh_runtime.experiments.series_store import DbSeriesStore

    data = _FakeDataClient()
    store = DbSeriesStore(lambda: data)
    stored = store.create(_series_record())
    entry, replayed = store.begin_run(
        stored.series_id, variant_id="off", idempotency_key=None, request_hash="h"
    )
    assert not replayed
    store.cancel_run(stored.series_id, entry["run_key"])
    record = store.get(stored.series_id)
    assert record.runs == []  # 排队条目已回滚,同键重试可重新发起
    entry2, _ = store.begin_run(
        stored.series_id, variant_id="off", idempotency_key=None, request_hash="h"
    )
    assert entry2["run_key"] == "run-001"  # 序号不因回滚而跳号
