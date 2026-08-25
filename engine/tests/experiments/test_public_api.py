"""匿名公共测试接口测试:Cookie 身份、字段白名单、repeat_count 校验与隔离。

全部使用注入的假执行器与临时任务存储,不访问真实 LLM 或数据服务。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import bdlh_runtime.run_api as run_api
from bdlh_runtime.experiments.job_store import JobStore, sha256_hex
from bdlh_runtime.experiments.public_service import AnonymousJobService


def _fake_comparison_executor(job):
    return {
        "runs": [
            {"unit_id": unit.unit_id, "task_success": True, "validity": "VALID",
             "stop_reason": "FINAL_ANSWER", "actual_agent_steps": 2, "duration_ms": 5}
            for unit in job.units
        ],
        "total_runs": len(job.units),
        "test_type": job.test_type,
    }


def _fake_compression_executor(job, should_stop=lambda: False):
    return {"cells": [], "stats": {}}


def _client(tmp_path, *, repository=None):
    from tests.experiments.test_jobs import MemoryRepo, _case

    store = JobStore(tmp_path / "jobs")
    service = AnonymousJobService(
        store,
        case_repository=repository or MemoryRepo([_case()]),
        comparison_executor=_fake_comparison_executor,
        compression_executor=_fake_compression_executor,
        thread_factory=lambda target: (target(), None)[1],  # 同步执行
    )
    original = run_api._public_service
    run_api._public_service = service
    run_api._job_store = store
    client = TestClient(run_api.app)
    yield client
    run_api._public_service = original


def test_production_service_wired_with_case_repository():
    """run_api 模块级生产服务必须带用例仓库(缺失时对比任务永远 400)。

    回归背景:曾漏传 case_repository,创建对比任务一律报
    「当前服务未配置用例库」;替身测试整体替换服务,无法暴露该装配缺失。
    client fixture 的 teardown 会把 _public_service 恢复为生产实例,此处直检。
    """
    import bdlh_runtime.run_api as api

    assert api._public_service.case_repository is not None, (
        "生产 AnonymousJobService 未接用例仓库,对比用例任务无法创建"
    )


@pytest.fixture()
def client(tmp_path):
    yield from _client(tmp_path)


def test_options_issues_anonymous_cookie(client):
    response = client.get("/api/v1/public/test-options")
    assert response.status_code == 200
    cookie = response.cookies.get("ts_anon")
    assert cookie and len(cookie) >= 20
    payload = response.json()
    assert payload["fixed_conditions"]["repeat_options"] == [3, 5]
    assert payload["fixed_conditions"]["run_counts"] == {
        "comparison_repeat_3": 9,
        "comparison_repeat_5": 15,
        "compression_session_matrix": 12,
        "compression_all_sessions_theoretical": 36,
    }
    # 公开选项不含评判配置与 gold
    assert "call_relation" not in response.text and "gold" not in response.text


def test_create_comparison_job_rejects_bad_repeat(client):
    for bad in (1, 2, 4, 7):
        response = client.post(
            "/api/v1/public/test-jobs",
            json={"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": bad},
        )
        assert response.status_code == 400, bad
        assert "repeat_count" in response.json()["detail"]


def test_create_comparison_job_rejects_custom_inputs(client):
    for field in ("message", "system_prompt", "tool_schema", "mock_result", "model_base_url", "api_key"):
        response = client.post(
            "/api/v1/public/test-jobs",
            json={"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": 3, field: "x"},
        )
        assert response.status_code == 400, field


def test_create_job_returns_nine_units_and_not_publishable(client):
    response = client.post(
        "/api/v1/public/test-jobs",
        json={"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": 3},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["unit_count"] == 9
    assert payload["publishable"] is False  # 匿名运行固定不可发布


def test_anonymous_cannot_read_others_jobs(client):
    created = client.post(
        "/api/v1/public/test-jobs",
        json={"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": 3},
    ).json()
    # 另一个匿名身份(无同一 Cookie)看不到该任务
    stranger = TestClient(run_api.app)
    assert stranger.get(f"/api/v1/public/test-jobs/{created['job_id']}").status_code == 404
    assert stranger.post(f"/api/v1/public/test-jobs/{created['job_id']}/cancel").status_code == 404
    # 本人可读可取消(幂等)
    owner = client.get(f"/api/v1/public/test-jobs/{created['job_id']}")
    assert owner.status_code == 200
    assert client.post(f"/api/v1/public/test-jobs/{created['job_id']}/cancel").status_code == 200


def test_list_jobs_scoped_to_own_identity(client):
    client.post(
        "/api/v1/public/test-jobs",
        json={"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": 3},
    )
    mine = client.get("/api/v1/public/test-jobs")
    assert mine.status_code == 200
    rows = mine.json()
    assert len(rows) == 1 and rows[0]["total_units"] == 9
    stranger = TestClient(run_api.app).get("/api/v1/public/test-jobs")
    assert stranger.json() == []


def test_compression_context_only_creates_zero_units(client):
    response = client.post(
        "/api/v1/public/test-jobs",
        json={
            "test_type": "COMPRESSION_CASE",
            "session_id": "ctx-session-context-engine-debug-01",
            "execution_scope": "context-only",
        },
    )
    assert response.status_code == 200
    assert response.json()["unit_count"] == 0  # 只生成上下文:0 个 Agent 运行


def test_compression_full_matrix_creates_twelve_units(client):
    response = client.post(
        "/api/v1/public/test-jobs",
        json={
            "test_type": "COMPRESSION_CASE",
            "session_id": "ctx-session-context-engine-debug-01",
            "execution_scope": "full-matrix",
            "repeat_count": 1,
        },
    )
    assert response.status_code == 200
    assert response.json()["unit_count"] == 12
    # 压缩矩阵不接受其他重复次数
    bad = client.post(
        "/api/v1/public/test-jobs",
        json={
            "test_type": "COMPRESSION_CASE",
            "session_id": "ctx-session-context-engine-debug-01",
            "execution_scope": "full-matrix",
            "repeat_count": 3,
        },
    )
    assert bad.status_code == 400


def test_unknown_session_rejected(client):
    response = client.post(
        "/api/v1/public/test-jobs",
        json={
            "test_type": "COMPRESSION_CASE",
            "session_id": "ctx-session-touchstone-design-01",
            "execution_scope": "context-only",
        },
    )
    assert response.status_code == 400  # 展示用 Session 不属于压缩用例数据源


def test_results_response_hides_internal_fields(client):
    created = client.post(
        "/api/v1/public/test-jobs",
        json={"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": 3},
    ).json()
    detail = client.get(f"/api/v1/public/test-jobs/{created['job_id']}").json()
    assert "quota_snapshot" not in detail  # 公开视图不暴露内部快照
    assert detail["anonymous_id_hash"] == sha256_hex(client.cookies.get("ts_anon"))
