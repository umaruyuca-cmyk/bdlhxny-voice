"""匿名公共测试接口测试:Cookie 身份、字段白名单、repeat_count 校验与隔离。

全部使用注入的假执行器与临时任务存储,不访问真实 LLM 或数据服务。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import bdlh_runtime.run_api as run_api
from bdlh_runtime.experiments.job_store import JobStore, sha256_hex
from bdlh_runtime.experiments.public_service import AnonymousJobService


def _fake_template_executor(job, should_stop=lambda: False):
    return {
        "runs": [
            {
                "unit_id": unit.unit_id,
                "task_success": True,
                "validity": "VALID",
                "stop_reason": "FINAL_ANSWER",
                "actual_agent_steps": 2,
                "duration_ms": 5,
                "answer": "上海今天多云,25℃。",
                "tool_calls": [
                    {
                        "sequence": 1,
                        "toolName": "weather.get_forecast",
                        "arguments": {"location": "上海"},
                        "status": "SUCCESS",
                        "resultSummary": {"status": "success", "forecast": "多云 25℃"},
                    }
                ],
                "model_calls": [
                    {
                        "sequence": 1,
                        "decision": "call_tool",
                        "status": "COMPLETE",
                        "durationMs": 1200,
                        "inputTokens": 800,
                        "outputTokens": 60,
                        "responseSummary": {
                            "decision": "call_tool",
                            "toolCalls": [{"name": "weather.get_forecast", "arguments": {"location": "上海"}}],
                            "textExcerpt": "我先查一下天气",
                        },
                        "messages": [{"role": "system", "content": "内部系统提示"}],
                        "requestedParams": {"temperature": 0.1},
                    }
                ],
                "audits": [{"auditCode": "G3-SCOPE-001"}],
                "events": [{"sequence": 1}],
            }
            for unit in job.units
        ],
        "total_runs": len(job.units),
        "test_type": job.test_type,
    }


def _fake_compression_executor(job, should_stop=lambda: False):
    return {"cells": [], "stats": {}}


#: 匿名可用的对比模板(governance-on-off:2 变体 × repeat_count)
TEMPLATE_ID = "governance-on-off"


def _client(tmp_path, *, repository=None):
    from tests.experiments.test_jobs import MemoryRepo, _case

    store = JobStore(tmp_path / "jobs")
    service = AnonymousJobService(
        store,
        case_repository=repository or MemoryRepo([_case()]),
        template_executor=_fake_template_executor,
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

    assert api._public_service.case_repository is not None, "生产 AnonymousJobService 未接用例仓库,对比用例任务无法创建"


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
    assert payload["fixed_conditions"]["agent_mode_ids"] == ["native-tool-calling"]
    # 一次只运行一个 Agent(P0-1):一次四运行的 native-matrix 口径不再下发
    assert "run_counts" not in payload["fixed_conditions"]
    # 公开选项不含评判配置与 gold
    assert "call_relation" not in response.text and "gold" not in response.text


def test_options_expose_tool_exclusion_presets(client):
    """发起页 tool-availability-degradation 档位下拉数据源:预设只暴露编号/说明/数量。"""
    body = client.get("/api/v1/public/test-options").json()
    presets = body.get("tool_exclusion_presets") or []
    ids = [row["preset_id"] for row in presets]
    assert "remove-preferred" in ids
    assert all("excluded_tools" not in row for row in presets)
    assert all(row["description"] for row in presets)


def test_create_comparison_job_rejects_bad_repeat(client):
    """对比模板 repeat_count 超出模板区间(1..5)一律拒绝。"""
    for bad in (0, 6, 7):
        response = client.post(
            "/api/v1/public/test-jobs",
            json={"test_type": "COMPARISON_CASE", "template_id": TEMPLATE_ID, "case_id": "cmp-x", "repeat_count": bad},
        )
        assert response.status_code == 400, bad
        assert "repeat_count" in response.json()["detail"]


def test_create_comparison_job_without_template_rejected(client):
    """对比任务必须携带 template_id:缺 template_id 拒绝。"""
    response = client.post(
        "/api/v1/public/test-jobs",
        json={"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": 3},
    )
    assert response.status_code == 400
    assert "模板" in response.json()["detail"]


def test_create_comparison_job_rejects_custom_inputs(client):
    for field in ("message", "system_prompt", "tool_schema", "mock_result", "model_base_url", "api_key"):
        response = client.post(
            "/api/v1/public/test-jobs",
            json={
                "test_type": "COMPARISON_CASE",
                "template_id": TEMPLATE_ID,
                "case_id": "cmp-x",
                "repeat_count": 3,
                field: "x",
            },
        )
        assert response.status_code == 400, field


def test_create_template_job_rejects_multi_run_expansion(client):
    """一次只运行一个 Agent(P0-1):匿名模板任务不再展开全部变体 × 重复。

    多运行入口明确关闭(400),不保留隐式批量执行;对比实验请登录后
    从实验组流程逐样本发起,或用 variant_label 选单个变体发起 1 次运行。
    """
    response = client.post(
        "/api/v1/public/test-jobs",
        json={"test_type": "COMPARISON_CASE", "template_id": TEMPLATE_ID, "case_id": "cmp-x", "repeat_count": 3},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "一次会展开" in detail and "入口已关闭" in detail


def test_create_anonymous_single_variant_run(client):
    """匿名单变体口径:variant_label 选模板既有变体之一,恰好创建 1 个运行。"""
    response = client.post(
        "/api/v1/public/test-jobs",
        json={
            "test_type": "COMPARISON_CASE",
            "template_id": TEMPLATE_ID,
            "case_id": "cmp-x",
            "repeat_count": 1,
            "variant_label": "off",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["unit_count"] == 1
    assert payload["publishable"] is False  # 匿名运行固定不可发布
    detail = client.get(f"/api/v1/public/test-jobs/{payload['job_id']}").json()
    assert len(detail["units"]) == 1
    assert detail["units"][0]["context_variant"] == "off"
    assert detail["status"] == "COMPLETE"  # 同步假执行器正常完成
    # 公开结果携带逐次运行明细(脱敏投影):工具名/参数/状态/世界返回摘要
    # 与模型调用逐步证据(responseSummary = 模型自己的决策与返回)保留;
    # 输入消息快照(messages)、请求参数三态、治理审计全量、事件流必须剥离
    results = client.get(f"/api/v1/public/test-jobs/{payload['job_id']}/results").json()
    runs = results["result"]["runs"]
    assert len(runs) == 1
    assert runs[0]["answer"] == "上海今天多云,25℃。"
    tool = runs[0]["tool_calls"][0]
    assert tool["toolName"] == "weather.get_forecast"
    assert tool["arguments"] == {"location": "上海"}
    assert tool["status"] == "SUCCESS"
    assert tool["resultSummary"] == {"status": "success", "forecast": "多云 25℃"}
    call = runs[0]["model_calls"][0]
    assert call["decision"] == "call_tool"
    assert call["responseSummary"]["textExcerpt"] == "我先查一下天气"
    assert call["responseSummary"]["toolCalls"][0]["name"] == "weather.get_forecast"
    # 脱敏边界:输入消息与请求参数不进公开投影
    assert "messages" not in call
    assert "requestedParams" not in call
    assert "audits" not in runs[0]
    assert "events" not in runs[0]
    assert "model_calls" in runs[0]  # 逐步模型调用证据在


def test_anonymous_single_variant_fixed_to_one_repeat(client):
    """匿名单变体运行固定 1 次;repeat_count>1 拒绝并说明。"""
    response = client.post(
        "/api/v1/public/test-jobs",
        json={
            "test_type": "COMPARISON_CASE",
            "template_id": TEMPLATE_ID,
            "case_id": "cmp-x",
            "repeat_count": 3,
            "variant_label": "off",
        },
    )
    assert response.status_code == 400
    assert "固定 1 次" in response.json()["detail"]


def test_anonymous_single_variant_rejects_unknown_variant(client):
    """variant_label 只能在模板既有变体中选择(不能提交任意变体)。"""
    response = client.post(
        "/api/v1/public/test-jobs",
        json={
            "test_type": "COMPARISON_CASE",
            "template_id": TEMPLATE_ID,
            "case_id": "cmp-x",
            "repeat_count": 1,
            "variant_label": "no-such",
        },
    )
    assert response.status_code == 400
    assert "变体标签" in response.json()["detail"]


def _create_compression_job(client):
    return client.post(
        "/api/v1/public/test-jobs",
        json={
            "test_type": "COMPRESSION_CASE",
            "session_id": "ctx-session-context-engine-debug-01",
            "execution_scope": "context-only",
        },
    )


def test_compression_job_is_not_publishable(client):
    response = _create_compression_job(client)
    assert response.status_code == 200
    payload = response.json()
    assert payload["unit_count"] == 0
    assert payload["publishable"] is False  # 匿名运行固定不可发布


def test_anonymous_cannot_read_others_jobs(client):
    created = _create_compression_job(client).json()
    # 另一个匿名身份(无同一 Cookie)看不到该任务
    stranger = TestClient(run_api.app)
    assert stranger.get(f"/api/v1/public/test-jobs/{created['job_id']}").status_code == 404
    assert stranger.post(f"/api/v1/public/test-jobs/{created['job_id']}/cancel").status_code == 404
    # 本人可读可取消(幂等)
    owner = client.get(f"/api/v1/public/test-jobs/{created['job_id']}")
    assert owner.status_code == 200
    assert client.post(f"/api/v1/public/test-jobs/{created['job_id']}/cancel").status_code == 200


def test_list_jobs_scoped_to_own_identity(client):
    _create_compression_job(client)
    mine = client.get("/api/v1/public/test-jobs")
    assert mine.status_code == 200
    rows = mine.json()
    assert len(rows) == 1 and rows[0]["total_units"] == 0
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


def test_compression_native_matrix_entry_closed(client):
    """一次只运行一个 Agent(P0-1):native-matrix 一次四运行入口明确关闭。"""
    response = client.post(
        "/api/v1/public/test-jobs",
        json={
            "test_type": "COMPRESSION_CASE",
            "session_id": "ctx-session-context-engine-debug-01",
            "execution_scope": "native-matrix",
            "repeat_count": 1,
        },
    )
    assert response.status_code == 400
    assert "入口已关闭" in response.json()["detail"]


def test_unknown_session_rejected(client):
    response = client.post(
        "/api/v1/public/test-jobs",
        json={
            "test_type": "COMPRESSION_CASE",
            "session_id": "ctx-showcase-01",
            "execution_scope": "context-only",
        },
    )
    assert response.status_code == 400  # 展示用 Session 不属于压缩用例数据源


def test_results_response_hides_internal_fields(client):
    created = _create_compression_job(client).json()
    detail = client.get(f"/api/v1/public/test-jobs/{created['job_id']}").json()
    assert "quota_snapshot" not in detail  # 公开视图不暴露内部快照
    assert detail["anonymous_id_hash"] == sha256_hex(client.cookies.get("ts_anon"))


def test_context_artifact_download_scoped_to_owner(client, tmp_path, monkeypatch):
    """上下文工件下载:本人可取,变体白名单外与陌生身份一律 404。"""
    from bdlh_runtime.experiments import compression as compression_module

    compiled_dir = tmp_path / "ctx-session-context-engine-debug-01" / "compiled"
    compiled_dir.mkdir(parents=True)
    (compiled_dir / "budgeted-session.json").write_text('{"variant_id": "budgeted-session"}', encoding="utf-8")
    monkeypatch.setattr(compression_module, "CASES_ROOT", tmp_path)

    created = client.post(
        "/api/v1/public/test-jobs",
        json={
            "test_type": "COMPRESSION_CASE",
            "template_id": "context-strategy-comparison",
            "session_id": "ctx-session-context-engine-debug-01",
            "execution_scope": "context-only",
            "repeat_count": 1,
        },
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]

    ok = client.get(f"/api/v1/public/test-jobs/{job_id}/context-artifacts/budgeted-session")
    assert ok.status_code == 200
    assert ok.json()["variant_id"] == "budgeted-session"
    # 变体白名单外按不存在处理
    assert client.get(f"/api/v1/public/test-jobs/{job_id}/context-artifacts/no-such").status_code == 404
    # 陌生匿名身份(无同一 Cookie)不可下载
    stranger = TestClient(run_api.app)
    assert stranger.get(f"/api/v1/public/test-jobs/{job_id}/context-artifacts/budgeted-session").status_code == 404
