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
