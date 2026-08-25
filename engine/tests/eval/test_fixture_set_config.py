"""GT-2:冻结集按批次可配——fixture_set_id 从请求到 get_tool_fixtures 的透传。

透传链:POST /api/v1/eval-batches(fixture_set_id)→ run_ab_eval(fixture_set_id)
→ DataClient.get_tool_fixtures(fixture_set_id);报告 JSON 与落库
fixedConditions/modelConfig 增记 fixtureSetId。deep_search 冻结行经
changes/ SQL 补录,镜像同步由 test_frozen_fixture_sync 守卫。
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

import bdlh_runtime.evaluation.ab_eval as ab_eval_module
import bdlh_runtime.run_api as run_api
from bdlh_runtime.evaluation.ab_eval import ABCase, _report_payload, run_ab_eval
from bdlh_runtime.evaluation.frozen_observations import FrozenObservations
from tests.eval.frozen_fixtures import frozen_payload
from tests.eval.test_run_api import FakeDataClient, _auth, _sample_recorder
from tests.eval.test_run_telemetry import ScriptedToolModel
from tests.registry.seeded_store import build_seeded_store


def _catalog_payload() -> dict[str, Any]:
    """构建与 GET /internal/v1/tool-catalog 同构的 payload(源自种子替身)。"""
    store = build_seeded_store()
    return {
        "operations": [{"code": op.code, "description": op.description} for op in store.operations],
        "toolsets": [{"name": ts.name, "description": ts.description} for ts in store.toolsets],
        "capabilities": [
            {
                "name": cap.name,
                "description": cap.description,
                "domain": cap.domain,
                "adapter": cap.adapter,
                "read_only": cap.read_only,
                "requires_authenticated_user": cap.requires_authenticated_user,
                "required_arguments": sorted(cap.required_arguments),
                "depends_on": sorted(cap.depends_on),
                "timeout_seconds": cap.timeout_seconds,
                "enabled": cap.enabled,
                "operations": sorted(cap.operations),
                "toolsets": sorted(cap.toolsets),
            }
            for cap in store.capabilities
        ],
        "skills": [
            {
                "skill_id": sk.skill_id,
                "skill_version": sk.skill_version,
                "domain": sk.domain,
                "status": sk.status,
                "enabled": sk.enabled,
                "operations": [{"code": code, "required": req} for code, req in sorted(sk.operations)],
                "capabilities": [{"capability": name, "required": req} for name, req in sorted(sk.capabilities)],
            }
            for sk in store.skills
        ],
    }


class CapturingDataClient:
    """替身 DataClient:记录 get_tool_fixtures 入参,返回目录与冻结 payload。"""

    def __init__(self) -> None:
        self.fixture_calls: list[tuple[str, int]] = []

    def get_tool_catalog(self) -> dict[str, Any]:
        return _catalog_payload()

    def get_tool_fixtures(self, fixture_set_id: str, *, version: int = 1) -> dict[str, Any]:
        self.fixture_calls.append((fixture_set_id, version))
        return frozen_payload()


def _case() -> ABCase:
    return ABCase(
        id="research-01",
        category="金融研究",
        message="宁德时代现在什么价",
        scene_tag="market",
        expected_tools=("market.get_realtime_quote",),
        case_version=1,
        variant_id="default",
        snapshot_id="research-01:fixture-v1",
        snapshot_hash="sha256:snap",
    )


async def _run(monkeypatch: pytest.MonkeyPatch, **kwargs: Any):
    from bdlh_runtime.scenarios import disable_all_scenario_packs, enable_scenario_pack

    enable_scenario_pack("finance")
    try:
        data = CapturingDataClient()
        monkeypatch.setattr(ab_eval_module, "DataClient", lambda: data)
        report = await run_ab_eval(
            llm=ScriptedToolModel(),
            model="glm-4.7-flash",
            cases=[_case()],
            with_react=False,
            retry_delay_s=0,
            inter_run_delay_s=0,
            **kwargs,
        )
        return data, report
    finally:
        disable_all_scenario_packs()


@pytest.mark.asyncio
async def test_fixture_set_id_defaults_to_ab_eval(monkeypatch: pytest.MonkeyPatch) -> None:
    data, report = await _run(monkeypatch)
    assert data.fixture_calls == [("ab-eval", 1)]
    assert report.fixture_set_id == "ab-eval"
    assert _report_payload(report)["fixture_set_id"] == "ab-eval"


@pytest.mark.asyncio
async def test_fixture_set_id_passthrough_to_data_client(monkeypatch: pytest.MonkeyPatch) -> None:
    data, report = await _run(monkeypatch, fixture_set_id="mock-eval-v1")
    assert data.fixture_calls == [("mock-eval-v1", 1)]
    assert report.fixture_set_id == "mock-eval-v1"
    assert _report_payload(report)["fixture_set_id"] == "mock-eval-v1"


def test_deep_search_frozen_row_is_served() -> None:
    """GT-2 补录验证:deep_search 不再吃 unknown tool 失败桩。"""
    frozen = FrozenObservations(frozen_payload())
    result = frozen.get("research.deep_search")
    assert "conclusion" in result and result["sources"]
    assert frozen.get("market.get_realtime_quote")["price"] == 185.50


class RecordingBatchDataClient(FakeDataClient):
    """在 FakeDataClient 基础上捕获 create_batch 的 fixedConditions。"""

    def __init__(self) -> None:
        super().__init__()
        self.fixed_conditions: dict[str, Any] | None = None

    def create_batch(self, *, name: str, fixed_conditions: dict[str, Any]) -> str:
        self.fixed_conditions = fixed_conditions
        return "batch-1"


def _post_batch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, body: dict[str, Any]
) -> tuple[RecordingBatchDataClient, dict[str, Any]]:
    data = RecordingBatchDataClient()
    monkeypatch.setattr(run_api, "_data", lambda: data)
    monkeypatch.setattr(run_api, "ARTIFACTS_DIR", tmp_path)
    recorder = _sample_recorder("baseline-tool-calling")

    def fake_execute(
        _request: Any, _catalog: Any, job: Any = None, llm_config=None
    ) -> tuple[dict[str, Any], list[Any]]:
        return {"run_records": [{"run_key": recorder.record.run_key, "run_id": None}]}, [recorder.record]

    monkeypatch.setattr(run_api, "_execute_eval", fake_execute)
    client = TestClient(run_api.app)
    response = client.post("/api/v1/eval-batches", json=body, headers=_auth())
    assert response.status_code == 200
    deadline = time.monotonic() + 5
    while True:
        job = client.get(f"/api/v1/jobs/{response.json()['job_id']}", headers=_auth()).json()
        if job["status"] != "running":
            break
        assert time.monotonic() < deadline, "作业未完成"
        time.sleep(0.02)
    assert job["status"] == "done", job.get("error")
    return data, job


def test_batch_records_fixture_set_id_in_conditions_and_model_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """指定 fixture_set_id:fixedConditions 与逐运行 modelConfig 均落键。"""
    data, _job = _post_batch(
        monkeypatch,
        tmp_path,
        {"case_ids": ["research-01"], "runs": 1, "include_react": False, "fixture_set_id": "ab-eval-negative-v1"},
    )
    assert data.fixed_conditions is not None
    assert data.fixed_conditions["fixtureSetId"] == "ab-eval-negative-v1"
    assert data.created_runs[0]["modelConfig"]["fixtureSetId"] == "ab-eval-negative-v1"


def test_batch_defaults_fixture_set_id_to_ab_eval(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """缺省:落库侧显式记录 ab-eval(配置随批次可见,不靠隐式约定)。"""
    data, _job = _post_batch(monkeypatch, tmp_path, {"case_ids": ["research-01"], "runs": 1, "include_react": False})
    assert data.fixed_conditions is not None
    assert data.fixed_conditions["fixtureSetId"] == "ab-eval"
    assert data.created_runs[0]["modelConfig"]["fixtureSetId"] == "ab-eval"
