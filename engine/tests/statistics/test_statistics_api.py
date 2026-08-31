"""统计端点测试(P0-7):鉴权 + 工件兜底重算 + 404,不访问任何模型服务。"""

from __future__ import annotations

import json

import pytest


@pytest.fixture()
def owner_client():
    from fastapi.testclient import TestClient

    from bdlh_runtime import run_api

    client = TestClient(run_api.app)
    client.app.dependency_overrides[run_api.require_login] = lambda: {"username": "owner"}
    yield client
    client.app.dependency_overrides.clear()


def _write_report(tmp_path, batch_id: str = "batch-stat-01") -> dict:
    report = {
        "template_id": "temperature-stability",
        "template_version": 1,
        "fixed_conditions_hash": "sha256:fixed",
        "runs": [
            {
                "run_id": "r1",
                "variant_label": "t0.0",
                "repeat_index": 1,
                "config_hash": "c1",
                "validity": "VALID",
                "stop_reason": "COMPLETED",
                "actual_agent_steps": 2,
                "duration_ms": 800,
                "tool_calls": [],
                "error": None,
            },
            {
                "run_id": "r2",
                "variant_label": "t0.7",
                "repeat_index": 1,
                "config_hash": "c1",
                "validity": "INVALID",
                "stop_reason": "ERROR",
                "actual_agent_steps": 0,
                "duration_ms": 0,
                "tool_calls": [],
                "error": "LLM_UNAVAILABLE: 未配置",
            },
        ],
    }
    (tmp_path / f"{batch_id}.json").write_text(json.dumps(report), encoding="utf-8")
    return report


def test_statistics_endpoint_rebuilds_from_artifact(owner_client, tmp_path, monkeypatch):
    from bdlh_runtime import run_api

    _write_report(tmp_path)
    monkeypatch.setattr(run_api, "ARTIFACTS_DIR", tmp_path)

    def _no_data():
        raise RuntimeError("data 服务不可达,走工件兜底")

    monkeypatch.setattr(run_api, "_data", _no_data)
    response = owner_client.get("/api/v1/statistics/batches/batch-stat-01")
    assert response.status_code == 200
    payload = response.json()
    assert payload["template_id"] == "temperature-stability"
    assert payload["definition_hash"] == "sha256:fixed"
    assert payload["included_run_ids"] == ["r1"]
    assert payload["excluded_runs"][0]["reason"] == "LLM_UNAVAILABLE"
    assert payload["by_variant"]["t0.0"]["sample_level"]["level"] == "single-observation"


def test_statistics_endpoint_404_when_no_report(owner_client, tmp_path, monkeypatch):
    from bdlh_runtime import run_api

    monkeypatch.setattr(run_api, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(run_api, "_data", lambda: None)
    response = owner_client.get("/api/v1/statistics/batches/missing")
    assert response.status_code == 404


def test_batch_statistics_reads_frozen_formal_min(owner_client, tmp_path, monkeypatch):
    """批次口径:正式样本门槛从报告冻结条件读取(缺省 3)。"""
    from bdlh_runtime import run_api

    batch_id = "batch-stat-formal"
    report = _write_report(tmp_path, batch_id)
    report["fixed_conditions"] = {"formal_min_repeat_count": 1}
    (tmp_path / f"{batch_id}.json").write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(run_api, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(run_api, "_data", lambda: None)

    payload = owner_client.get(f"/api/v1/statistics/batches/{batch_id}").json()
    # 门槛 1:批次口径无预期配置哈希(观察主导值兼容口径),样本量达标也
    # 只标"观察结果",不冒充"最小正式样本"(修复方案 P1-2)
    assert payload["formal_min_repeat_count"] == 1
    assert payload["config_hash_mode"] == "observed-dominant"
    assert payload["by_variant"]["t0.0"]["sample_level"]["level"] == "observed-compat"
    assert payload["comparison"]["formal_available"] is False

    # 无冻结条件的旧报告回退缺省 3,1 个样本保持单次观察,并在 notes 中明示回退
    del report["fixed_conditions"]
    (tmp_path / f"{batch_id}.json").write_text(json.dumps(report), encoding="utf-8")
    legacy = owner_client.get(f"/api/v1/statistics/batches/{batch_id}").json()
    assert legacy["formal_min_repeat_count"] == 3
    assert legacy["by_variant"]["t0.0"]["sample_level"]["level"] == "single-observation"
    assert any("formal_min_repeat_count" in note for note in legacy["notes"])


def test_batch_statistics_reads_threshold_from_real_template_plan(owner_client, tmp_path, monkeypatch):
    """P1-4:门槛随真实模板计划冻结进报告,统计端读到的就是模板冻结值。"""
    from bdlh_runtime import run_api
    from bdlh_runtime.experiments.templates import ROLE_OWNER, plan_template_batch

    # governance-on-off:formal_min_repeat_count=3 的正式单变量模板(无能力门槛)
    plan = plan_template_batch("governance-on-off", repeat_count=1, role=ROLE_OWNER)
    assert plan.fixed_conditions["formal_min_repeat_count"] == 3
    batch_id = "batch-stat-real-plan"
    report = _write_report(tmp_path, batch_id)
    report["template_id"] = plan.template_id
    report["fixed_conditions"] = plan.fixed_conditions
    (tmp_path / f"{batch_id}.json").write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(run_api, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(run_api, "_data", lambda: None)

    payload = owner_client.get(f"/api/v1/statistics/batches/{batch_id}").json()
    assert payload["formal_min_repeat_count"] == 3
    # 真实计划不再触发兼容回退提示
    assert not any("回退兼容默认值" in note for note in payload["notes"])
