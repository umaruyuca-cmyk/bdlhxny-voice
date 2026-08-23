"""私有运行 API:固定题号、fail-closed 鉴权和数据服务持久化。"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

import bdlh_runtime.run_api as run_api
from bdlh_runtime.evaluation.run_telemetry import RunRecorder


class FakeDataClient:
    def __init__(self) -> None:
        self.created_runs: list[dict[str, Any]] = []
        self.completed: list[str] = []
        self.completed_payloads: list[dict[str, Any]] = []
        self.saved_events: list[tuple[str, list[dict[str, Any]]]] = []
        self.saved_model_calls: list[tuple[str, list[dict[str, Any]]]] = []
        self.saved_tool_calls: list[tuple[str, list[dict[str, Any]]]] = []
        self.saved_guardrail_checks: list[tuple[str, list[dict[str, Any]]]] = []
        self.saved_measurements: list[tuple[str, dict[str, Any]]] = []
        self.saved_artifacts: list[tuple[str, dict[str, Any]]] = []
        self.evaluations: list[tuple[str, dict[str, Any]]] = []
        self.saved_context_builds: list[tuple[str, dict[str, Any]]] = []

    def get_llm_config(self, account_id: str) -> dict[str, Any] | None:
        return None

    def get_case_variant_context(self, case_id: str, version: int, variant_id: str) -> dict[str, Any]:
        return {
            "caseId": case_id,
            "caseVersion": version,
            "variantId": variant_id,
            "contextStrategy": "budgeted" if variant_id == "budgeted-comp" else "full",
            "tokenBudget": 12288 if variant_id == "budgeted-comp" else 65536,
            "source": "data_fixture",
            "items": [
                {
                    "itemKey": "rule-no-trading",
                    "itemType": "rule",
                    "classification": "required",
                    "content": "不得自动下单。",
                    "priority": 100,
                    "trusted": True,
                    "sequence": 0,
                    "untrusted": False,
                    "stale": False,
                    "validFrom": None,
                    "validTo": None,
                    "crossUser": False,
                    "duplicateOf": None,
                    "observedAt": None,
                }
            ],
        }

    def save_context_build(self, run_id: str, build: dict[str, Any]) -> None:
        self.saved_context_builds.append((run_id, build))

    def list_cases(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "research-01",
                "version": 1,
                "title": "实时行情工具选择",
                "message": "宁德时代现在什么价",
                "scene": "market",
                "authenticated": False,
                "expectedChecks": {
                    "category": "金融研究",
                    "expected_tools": ["market.get_realtime_quote"],
                },
                "steps": [],
                "variants": [
                    {
                        "variantId": "default",
                        "contextStrategy": "budgeted",
                        "tokenBudget": 8192,
                        "snapshotId": "research-01:fixture-v1",
                        "snapshotHash": "sha256:snap",
                    }
                ],
            },
            {
                "id": "ctx-mini-port",
                "version": 1,
                "title": "迷你组合诊断",
                "message": "我的持仓现在值多少钱?",
                "scene": "market",
                "authenticated": False,
                "expectedChecks": {"category": "长上下文·组合", "expected_tools": ["market.get_realtime_quote"]},
                "steps": [],
                "variants": [
                    {
                        "variantId": "full-raw",
                        "contextStrategy": "full",
                        "tokenBudget": 65536,
                        "snapshotId": "ctx-mini-port:full-raw:fixture-v1",
                        "snapshotHash": "sha256:p1",
                    },
                    {
                        "variantId": "budgeted-comp",
                        "contextStrategy": "budgeted",
                        "tokenBudget": 12288,
                        "snapshotId": "ctx-mini-port:budgeted-comp:fixture-v1",
                        "snapshotHash": "sha256:p2",
                    },
                ],
            },
        ]

    def get_tool_catalog(self) -> dict[str, Any]:
        """最小目录 payload(与 data 服务 /tool-catalog 同构;GT-4 校验与端点消费)。"""
        return {
            "operations": [{"code": "READ_MARKET_DATA", "description": "读取公开市场数据"}],
            "toolsets": [{"name": "market_read", "description": "行情读取"}],
            "capabilities": [
                {
                    "name": name,
                    "description": f"{name} description",
                    "domain": name.split(".")[0],
                    "adapter": "mcp",
                    "read_only": True,
                    "requires_authenticated_user": False,
                    "required_arguments": ["symbol"],
                    "depends_on": [],
                    "timeout_seconds": 20,
                    "enabled": True,
                    "operations": ["READ_MARKET_DATA"],
                    "toolsets": ["market_read"],
                }
                for name in ("market.get_realtime_quote", "market.get_valuation", "market.get_news")
            ],
            "skills": [],
        }

    def create_batch(self, **_: Any) -> str:
        return "batch-1"

    def get_batch(self, batch_id: str) -> dict[str, Any]:
        return {"id": batch_id, "status": "COMPLETE", "runs": []}

    def get_run_detail(self, run_id: str) -> dict[str, Any]:
        return {"id": run_id, "events": [], "toolCalls": [], "modelCalls": []}

    def verify_session(self, token: str) -> dict[str, Any] | None:
        if token == "test-token":
            return {"accountId": "owner", "username": "owner"}
        return None

    def create_run(self, payload: dict[str, Any]) -> str:
        self.created_runs.append(payload)
        return f"run-{len(self.created_runs)}"

    def complete_batch(self, batch_id: str, status: str) -> None:
        assert batch_id == "batch-1"
        assert status in {"COMPLETE", "FAILED", "CANCELLED"}

    def save_events(self, run_id: str, events: list[dict[str, Any]]) -> None:
        self.saved_events.append((run_id, events))

    def save_model_calls(self, run_id: str, calls: list[dict[str, Any]]) -> None:
        self.saved_model_calls.append((run_id, calls))

    def save_tool_calls(self, run_id: str, calls: list[dict[str, Any]]) -> None:
        self.saved_tool_calls.append((run_id, calls))

    def save_guardrail_checks(self, run_id: str, checks: list[dict[str, Any]]) -> None:
        self.saved_guardrail_checks.append((run_id, checks))

    def save_measurements(self, run_id: str, measurements: dict[str, Any]) -> None:
        self.saved_measurements.append((run_id, measurements))

    def save_artifact(self, run_id: str, **payload: Any) -> None:
        self.saved_artifacts.append((run_id, payload))

    def save_evaluation(self, run_id: str, **payload: Any) -> None:
        self.evaluations.append((run_id, payload))

    def complete_run(
        self,
        run_id: str,
        output: dict[str, Any],
        *,
        status: str = "COMPLETE",
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> None:
        assert "judgment" in output
        self.completed.append(run_id)
        self.completed_payloads.append({"run_id": run_id, "status": status, "error_category": error_category})


def _sample_recorder(agent_mode: str, *, status: str = "COMPLETE", error_category: str | None = None) -> RunRecorder:
    recorder = RunRecorder(
        run_key=f"research-01:{agent_mode}:0",
        case_id="research-01",
        case_version=1,
        variant_id="default",
        snapshot_id="research-01:fixture-v1",
        snapshot_hash="sha256:snap",
        agent_mode=agent_mode,
        context_strategy="fixed-case-input",
        model="glm-4.7-flash",
        repeat_index=0,
        message="宁德时代现在什么价",
        category="金融研究",
    )
    recorder.record_judgment({"tool_correct": True})
    recorder.complete(status=status, error_category=error_category, error_text="429" if error_category else None)
    return recorder


@pytest.fixture()
def fake_data(monkeypatch: pytest.MonkeyPatch) -> FakeDataClient:
    data = FakeDataClient()
    monkeypatch.setattr(run_api, "_data", lambda: data)
    return data


@pytest.fixture()
def client(fake_data: FakeDataClient) -> TestClient:
    return TestClient(run_api.app)


def test_health_is_public(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "run-api"


def test_interactive_docs_are_disabled(client: TestClient) -> None:
    """生产最小暴露：私有服务不开放 /docs 与 OpenAPI schema。"""
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_cors_disabled_by_default(client: TestClient) -> None:
    """RUN_API_ALLOWED_ORIGINS 未配置时 fail-closed：响应不带任何 CORS 头。"""
    response = client.options(
        "/api/v1/cases",
        headers={"Origin": "http://127.0.0.1:8082", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in response.headers


def test_cors_enabled_only_with_configured_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    """配置 /lab 来源后预检放行，且只放行配置值。"""
    import importlib

    monkeypatch.setenv("RUN_API_ALLOWED_ORIGINS", "http://127.0.0.1:8082")
    reloaded = importlib.reload(run_api)
    try:
        with TestClient(reloaded.app) as cors_client:
            preflight = cors_client.options(
                "/api/v1/cases",
                headers={
                    "Origin": "http://127.0.0.1:8082",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "authorization",
                },
            )
            assert preflight.status_code in (200, 204)
            assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:8082"

            disallowed = cors_client.options(
                "/api/v1/cases",
                headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
            )
            assert disallowed.headers.get("access-control-allow-origin") != "http://evil.example"
    finally:
        monkeypatch.delenv("RUN_API_ALLOWED_ORIGINS", raising=False)
        importlib.reload(run_api)


def test_requires_session_token(client: TestClient) -> None:
    assert client.get("/api/v1/cases").status_code == 401


def test_cases_are_read_from_data_service(client: TestClient) -> None:
    response = client.get("/api/v1/cases", headers=_auth())
    assert response.status_code == 200
    assert response.json()[0]["id"] == "research-01"


def test_completed_batch_can_be_read_after_job_memory_is_gone(client: TestClient) -> None:
    response = client.get("/api/v1/batches/batch-1", headers=_auth())
    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETE"


def test_run_detail_proxies_data_service(client: TestClient) -> None:
    response = client.get("/api/v1/runs/run-9/detail", headers=_auth())
    assert response.status_code == 200
    assert response.json()["id"] == "run-9"


def test_request_rejects_question_or_tool_fields(client: TestClient) -> None:
    response = client.post(
        "/api/v1/eval-batches",
        json={"case_ids": ["research-01"], "message": "任意问题"},
        headers=_auth(),
    )
    assert response.status_code == 422


def test_batch_persists_stepwise_records_for_each_mode(
    client: TestClient,
    fake_data: FakeDataClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """任务一验收:逐运行落库(事件/明细/测量/工件)且 run_id 回填 report。"""
    monkeypatch.setattr(run_api, "ARTIFACTS_DIR", tmp_path)
    recorders = [
        _sample_recorder("baseline-tool-calling"),
        _sample_recorder("langgraph-react"),
        _sample_recorder("full-system"),
    ]

    def fake_execute(
        _request: Any, _catalog: Any, job: Any = None, llm_config=None
    ) -> tuple[dict[str, Any], list[Any]]:
        payload = {
            "cases": [
                {
                    "id": "research-01",
                    "baseline": {"tool_correct": 1},
                    "react": {"tool_correct": 1},
                    "treatment": {"tool_correct": 1},
                    "lineage": [],
                }
            ],
            "run_records": [{"run_key": recorder.record.run_key, "run_id": None} for recorder in recorders],
        }
        return payload, [recorder.record for recorder in recorders]

    monkeypatch.setattr(run_api, "_execute_eval", fake_execute)
    response = client.post(
        "/api/v1/eval-batches",
        json={"case_ids": ["research-01"], "runs": 1},
        headers=_auth(),
    )
    assert response.status_code == 200
    job = _poll(client, response.json()["job_id"])
    assert job["status"] == "done"

    # 三组各一条运行记录,variant/snapshot 来自 data 服务视图(非拼接)
    assert [run["agentMode"] for run in fake_data.created_runs] == [
        "baseline-tool-calling",
        "langgraph-react",
        "full-system",
    ]
    for run in fake_data.created_runs:
        assert run["variantId"] == "default"
        assert run["snapshotId"] == "research-01:fixture-v1"

    # 事件流与测量逐运行写入
    assert len(fake_data.saved_events) == 3
    assert all(events and events[0]["eventType"] == "run.started" for _run_id, events in fake_data.saved_events)
    assert len(fake_data.saved_measurements) == 3
    assert len(fake_data.evaluations) == 3
    assert all(payload["valid_run"] for _run_id, payload in fake_data.evaluations)

    # 工件文件双写 + run_artifacts 登记 + hash 可复算
    assert len(fake_data.saved_artifacts) == 3
    for run_id, artifact_payload in fake_data.saved_artifacts:
        artifact_file = tmp_path / "runs" / f"{run_id}.json"
        assert artifact_file.is_file()
        import json as jsonlib

        artifact = jsonlib.loads(artifact_file.read_text(encoding="utf-8"))
        assert artifact["artifact_hash"] == artifact_payload["content_hash"]
        assert artifact["artifact_hash"].startswith("sha256:")

    # run_id 回填进 report
    assert [row["run_id"] for row in job["report"]["run_records"]] == ["run-1", "run-2", "run-3"]
    assert len(fake_data.completed) == 3


def test_invalid_run_is_not_marked_valid(
    client: TestClient,
    fake_data: FakeDataClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """429 注入运行:validRun=False、状态 INVALID、工件仍落盘。"""
    monkeypatch.setattr(run_api, "ARTIFACTS_DIR", tmp_path)
    recorder = _sample_recorder("baseline-tool-calling", status="INVALID", error_category="RATE_LIMITED")

    def fake_execute(
        _request: Any, _catalog: Any, job: Any = None, llm_config=None
    ) -> tuple[dict[str, Any], list[Any]]:
        return {"cases": [], "run_records": [{"run_key": recorder.record.run_key, "run_id": None}]}, [recorder.record]

    monkeypatch.setattr(run_api, "_execute_eval", fake_execute)
    response = client.post(
        "/api/v1/eval-batches",
        json={"case_ids": ["research-01"], "runs": 1, "include_react": False},
        headers=_auth(),
    )
    assert response.status_code == 200
    job = _poll(client, response.json()["job_id"])
    assert job["status"] == "done"
    assert fake_data.evaluations[0][1]["valid_run"] is False
    assert fake_data.evaluations[0][1]["status"] == "INVALID"
    # agent_runs.status 同源透传(不再恒 COMPLETE):状态与错误类别一并落库
    assert fake_data.completed_payloads[0]["status"] == "INVALID"
    assert fake_data.completed_payloads[0]["error_category"] == "RATE_LIMITED"
    assert fake_data.saved_artifacts[0][1]["content_hash"].startswith("sha256:")
    assert (tmp_path / "runs" / "run-1.json").is_file()


def test_unknown_case_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/eval-batches", json={"case_ids": ["missing"]}, headers=_auth())
    assert response.status_code == 400


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _poll(client: TestClient, job_id: str) -> dict[str, Any]:
    for _ in range(50):
        response = client.get(f"/api/v1/jobs/{job_id}", headers=_auth())
        assert response.status_code == 200
        if response.json()["status"] != "running":
            return response.json()
        time.sleep(0.02)
    raise AssertionError("作业未完成")


def test_context_batch_persists_variant_runs(
    client: TestClient,
    fake_data: FakeDataClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """任务二验收:压缩对照批次逐变体落库,context_builds 写入真实报告。"""
    monkeypatch.setattr(run_api, "ARTIFACTS_DIR", tmp_path)
    recorder = _sample_recorder("full-system")
    recorder.record.case_id = "ctx-mini-port"
    recorder.record.variant_id = "budgeted-comp"
    recorder.record.snapshot_id = "ctx-mini-port:budgeted-comp:fixture-v1"
    recorder.record.context_strategy = "budgeted"
    recorder.attach_context_build(
        {
            "strategy": "budgeted",
            "tokenizerVersion": "conservative-cjk1-latin4-v1",
            "compressionVersion": "structured-text-v1",
            "tokenBudget": 12288,
            "originalTokens": 9000,
            "workingTokens": 3000,
            "compressionInputTokens": 6000,
            "compressionOutputTokens": 2000,
            "durationMs": 12,
            "requiredRetained": True,
            "budgetFit": True,
            "referencesValid": True,
            "instructionIsolated": True,
            "status": "COMPLETE",
            "errorCode": None,
            "items": [
                {
                    "itemKey": "rule-no-trading",
                    "itemType": "rule",
                    "classification": "required",
                    "content": "不得自动下单。",
                    "sourceId": None,
                    "ownerId": None,
                    "observedAt": None,
                    "priority": 100,
                    "trusted": True,
                    "rawTokens": 9,
                    "contentHash": "sha256:c",
                    "sequence": 1,
                }
            ],
            "decisions": [
                {
                    "itemKey": "rule-no-trading",
                    "action": "kept",
                    "reason": "required item",
                    "inputTokens": 9,
                    "outputTokens": 9,
                    "outputContent": None,
                    "outputHash": None,
                    "referenceId": None,
                    "decisionOrder": 0,
                }
            ],
            "messages": [{"messageOrder": 0, "role": "system", "content": "s", "contentHash": "sha256:m", "tokens": 1}],
        }
    )
    recorder.complete(status="COMPLETE")

    def fake_execute(_request: Any, _views: Any, _selected: Any, llm_config=None) -> tuple[dict[str, Any], list[Any]]:
        return {
            "case_count": 1,
            "by_variant": {},
            "run_records": [{"run_key": recorder.record.run_key, "run_id": None}],
        }, [recorder.record]

    monkeypatch.setattr(run_api, "_execute_context_eval", fake_execute)
    response = client.post(
        "/api/v1/context-batches",
        json={"case_ids": ["ctx-mini-port"], "runs": 1},
        headers=_auth(),
    )
    assert response.status_code == 200
    job = _poll(client, response.json()["job_id"])
    assert job["status"] == "done", job.get("error")

    run_payload = fake_data.created_runs[0]
    assert run_payload["variantId"] == "budgeted-comp"
    assert run_payload["snapshotId"] == "ctx-mini-port:budgeted-comp:fixture-v1"
    assert run_payload["contextStrategy"] == "budgeted"
    assert len(fake_data.saved_context_builds) == 1
    build = fake_data.saved_context_builds[0][1]
    assert build["strategy"] == "budgeted"
    assert build["items"] and build["decisions"] and build["messages"]
    assert fake_data.saved_measurements[0][1]["contextCollectMs"] == 12
    assert job["report"]["run_records"][0]["run_id"] == "run-1"
    assert (tmp_path / "runs" / "run-1.json").is_file()


def test_context_batch_rejects_non_comparison_cases(client: TestClient) -> None:
    response = client.post(
        "/api/v1/context-batches",
        json={"case_ids": ["research-01"]},
        headers=_auth(),
    )
    assert response.status_code == 400


def test_select_case_views_filters_ids_and_skips_ctx_variants() -> None:
    """case_ids 必须真正过滤执行列表;全部题目时跳过无 default 变体的 ctx 用例。

    回归:此前 case_ids 只校验不过滤,目录含 ctx-* 用例(无 default 变体)时
    load_cases 直接抛"没有 default 变体",任何批次都失败。
    """
    catalog = [
        {"id": "research-01", "variants": [{"variantId": "default"}]},
        {"id": "ctx-port-01", "variants": [{"variantId": "full-raw"}, {"variantId": "budgeted-comp"}]},
        {"id": "chat-01", "variants": [{"variantId": "default"}]},
    ]
    picked = run_api._select_case_views(catalog, ["research-01", "ctx-port-01"])
    assert [view["id"] for view in picked] == ["research-01", "ctx-port-01"]
    default_only = run_api._select_case_views(catalog, None)
    assert [view["id"] for view in default_only] == ["research-01", "chat-01"]

def test_context_cases_list_ctx_library_metadata(client: TestClient, fake_data: FakeDataClient) -> None:
    """长上下文库端点:只列带对照变体的用例,带条目构成与 token 估算。"""
    response = client.get("/api/v1/context-cases", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    cases = response.json()
    assert [case["case_id"] for case in cases] == ["ctx-mini-port"]
    meta = cases[0]
    assert meta["item_count"] == 1
    assert meta["item_counts"]["required"] == 1
    assert meta["token_estimate"] > 0
    assert meta["variants"]["budgeted-comp"]["token_budget"] == 12288


def test_context_compress_runs_builder_without_llm(client: TestClient, fake_data: FakeDataClient) -> None:
    """压缩测试端点:只跑构建器,返回逐条决策与 token 口径,无模型调用。"""
    response = client.post(
        "/api/v1/context-compress",
        headers={"Authorization": "Bearer test-token"},
        json={"case_id": "ctx-mini-port"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETE"
    assert body["strategy"] == "budgeted"
    assert body["token_budget"] == 12288
    assert body["required_retained"] is True
    assert body["working_tokens"] <= body["token_budget"]
    assert body["decisions"] and body["decisions"][0]["action"] in {"kept", "compressed", "referenced", "omitted"}


def test_context_compress_rejects_unknown_case(client: TestClient, fake_data: FakeDataClient) -> None:
    response = client.post(
        "/api/v1/context-compress",
        headers={"Authorization": "Bearer test-token"},
        json={"case_id": "no-such-case"},
    )
    assert response.status_code == 400
    assert "未知" in response.json()["detail"]


def test_context_link_batch_rejects_unknown_case(client: TestClient, fake_data: FakeDataClient) -> None:
    response = client.post(
        "/api/v1/context-link-batches",
        headers={"Authorization": "Bearer test-token"},
        json={"case_ids": ["nope"], "runs": 1},
    )
    assert response.status_code == 400
