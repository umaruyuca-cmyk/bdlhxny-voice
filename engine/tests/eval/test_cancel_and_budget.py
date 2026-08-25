"""批次过程管理(任务四):协作取消与 token 上限。"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

import bdlh_runtime.run_api as run_api
from bdlh_runtime.evaluation.ab_eval import ABCase, run_ab_eval
from bdlh_runtime.evaluation.frozen_observations import FrozenObservations
from bdlh_runtime.tools.catalog import catalog_from_snapshot
from tests.eval.frozen_fixtures import frozen_payload
from tests.eval.test_run_api import FakeDataClient, _auth, _poll
from tests.eval.test_run_telemetry import ScriptedToolModel
from tests.helpers_registry import seeded_snapshot


@pytest.fixture()
def fake_data(monkeypatch: pytest.MonkeyPatch) -> FakeDataClient:
    data = FakeDataClient()
    monkeypatch.setattr(run_api, "_data", lambda: data)
    return data


@pytest.fixture()
def client(fake_data: FakeDataClient) -> TestClient:
    return TestClient(run_api.app)


def _case(case_id: str = "research-01") -> ABCase:
    return ABCase(
        id=case_id,
        category="金融研究",
        message="宁德时代现在什么价",
        scene_tag="market",
        expected_tools=("market.get_realtime_quote",),
        case_version=1,
        variant_id="default",
        snapshot_id=f"{case_id}:fixture-v1",
        snapshot_hash="sha256:snap",
    )


async def _run(**kwargs: Any):
    from bdlh_runtime.scenarios import disable_all_scenario_packs, enable_scenario_pack

    enable_scenario_pack("finance")
    try:
        return await run_ab_eval(
            llm=ScriptedToolModel(),
            model="glm-4.7-flash",
            cases=[_case()],
            catalog=catalog_from_snapshot(seeded_snapshot()),
            frozen=FrozenObservations(frozen_payload()),
            retry_delay_s=0,
            inter_run_delay_s=0,
            **kwargs,
        )
    finally:
        disable_all_scenario_packs()


@pytest.mark.asyncio
async def test_cooperative_cancel_stops_new_runs_and_keeps_partial() -> None:
    calls = {"n": 0}

    def should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 1  # 第一次检查放行,第二次(下一运行发起前)取消

    report = await _run(runs_per_case=2, with_react=False, should_stop=should_stop)
    assert calls["n"] == 2
    assert len(report.run_records) == 1  # 已开始的运行完成,后续不发起
    assert report.stop_reason == "CANCELLED"
    assert report.skipped_runs == 3  # 期望 4(1 题×2 次×2 组),完成 1
    # 部分完成语义:已完成运行事件流完整
    record = report.run_records[0]
    assert record.events[-1]["eventType"] == "run.completed"


@pytest.mark.asyncio
async def test_token_budget_stops_new_runs_without_invalid_runs() -> None:
    # ScriptedToolModel 每运行 2 次调用 × (120+30) = 300 tokens
    report = await _run(runs_per_case=1, with_react=True, max_total_tokens=450)
    assert len(report.run_records) == 2  # 第三个运行发起前停止(600 ≥ 450)
    assert report.stop_reason == "TOKEN_BUDGET_EXCEEDED"
    assert report.skipped_runs == 1
    # 停止 ≠ 无效:未发起的运行不产生 INVALID 记录;已完成运行全部 COMPLETE
    assert all(record.status == "COMPLETE" for record in report.run_records)


@pytest.mark.asyncio
async def test_no_budget_and_no_cancel_runs_everything() -> None:
    report = await _run(runs_per_case=1, with_react=False)
    assert report.stop_reason is None
    assert report.skipped_runs == 0
    assert len(report.run_records) == 2


def test_cancel_endpoint_cooperative_and_idempotent(
    fake_data,  # noqa: ANN001 — pytest fixture(engine/tests/eval/test_run_api.py 提供)
    monkeypatch,
    tmp_path,
):
    """验收:取消后作业进 CANCELLED 且工件完整;幂等重复取消无副作用。"""
    monkeypatch.setattr(run_api, "ARTIFACTS_DIR", tmp_path)
    from tests.eval.test_run_api import _sample_recorder

    def fake_execute(request, catalog, job=None, llm_config=None):  # noqa: ANN001,ARG001
        # 第一条运行立即完成(部分完成基础),随后模拟运行中等待协作取消
        recorder = _sample_recorder("baseline-tool-calling")
        deadline = time.monotonic() + 5
        while job is not None and not job.get("cancel_requested") and time.monotonic() < deadline:
            time.sleep(0.02)
        payload = {
            "cases": [],
            "run_records": [{"run_key": recorder.record.run_key, "run_id": None}],
            "stop_reason": "CANCELLED",
            "skipped_runs": 9,
        }
        return payload, [recorder.record]

    monkeypatch.setattr(run_api, "_execute_eval", fake_execute)
    client = TestClient(run_api.app)

    response = client.post(
        "/api/v1/eval-batches",
        json={"case_ids": ["research-01"], "runs": 5, "include_react": False},
        headers=_auth(),
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    # 运行中取消(协作标志,不硬杀);重复取消幂等
    first = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=_auth())
    assert first.status_code == 200
    assert first.json()["cancel_requested"] is True
    second = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=_auth())
    assert second.status_code == 200
    assert second.json() == first.json()

    job = _poll(client, job_id)
    assert job["status"] == "cancelled"
    assert job["report"]["stop_reason"] == "CANCELLED"
    # 已取消作业再取消:无副作用,返回终态
    again = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=_auth())
    assert again.status_code == 200
    assert again.json()["status"] == "cancelled"
    assert again.json()["cancel_requested"] is True
    # 部分完成:已完成运行的工件照常落库
    assert fake_data.created_runs, "已完成部分应照常落库"
    assert (tmp_path / "runs" / "run-1.json").is_file()
    # 批次以 CANCELLED 收尾(FakeDataClient.complete_batch 校验允许值)
    assert fake_data.completed


def test_cancel_unknown_job_is_404(client, finance_pack):  # noqa: ANN001
    assert client.post("/api/v1/jobs/missing/cancel", headers=_auth()).status_code == 404


def test_max_total_tokens_request_validation(client, finance_pack):  # noqa: ANN001
    response = client.post(
        "/api/v1/eval-batches",
        json={"case_ids": ["research-01"], "runs": 1, "max_total_tokens": 0},
        headers=_auth(),
    )
    assert response.status_code == 422
