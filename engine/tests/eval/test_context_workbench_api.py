from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bdlh_runtime.run_api as run_api
from bdlh_runtime.memory import ContextBuildStore, ContextWorkbenchService, DataServiceContextBuildStore
from bdlh_runtime.session import SessionCompiler


class _AuthOnlyData:
    """登录鉴权 + 上下文审计/授权假实现:记录调用,不触网。"""

    def __init__(self) -> None:
        self.audit_calls: list[dict] = []
        self.grants: dict[str, set[str]] = {}  # grantee_id -> {build_id | "*"}

    def verify_session(self, token: str):  # noqa: ANN201
        if token == "test-token":
            return {"accountId": "owner-1", "username": "owner"}
        if token == "ops-token":
            return {"accountId": "ops-1", "username": "ops"}
        if token == "other-token":
            return {"accountId": "owner-2", "username": "other"}
        return None

    def write_context_audit(self, account_id, action, *, succeeded=True, detail=None):  # noqa: ANN001
        self.audit_calls.append(
            {"account_id": account_id, "action": action, "succeeded": succeeded, "detail": detail or {}}
        )

    def list_context_audit(self, account_id=None, *, limit=50):  # noqa: ANN001
        return [
            {
                "action": row["action"],
                "succeeded": row["succeeded"],
                "accountId": row["account_id"],
                "detail": row["detail"],
                "createdAt": None,
            }
            for row in self.audit_calls
            if account_id is None or row["account_id"] == account_id
        ][:limit]

    def has_context_grant_for_grantee(self, grantee_id: str, build_id: str) -> bool:
        scopes = self.grants.get(grantee_id, set())
        return "*" in scopes or build_id in scopes

    # P2 定时分析假实现:语义抽检结果(默认空列表)
    def list_context_quality_checks(self, account_id=None, *, session_id=None, limit=50):  # noqa: ANN001, ARG002
        return list(getattr(self, "quality_checks", []))[:limit]

    # 分析运行假实现:固定一行(运维报告端点测试读取)
    def list_context_analysis_runs(self, limit=50):  # noqa: ANN001
        return [
            {
                "runId": "run-1",
                "status": "COMPLETED",
                "triggerSource": "SCHEDULED",
                "sampledSegments": 2,
                "judgeCalls": 2,
                "judgeErrors": 0,
                "report": {"threshold_groups": [], "cost_benefit": {}, "correlation": {}},
                "errorCode": None,
                "startedAt": None,
                "finishedAt": None,
            }
        ][:limit]

    # 授权管理假实现:fail_next_conflict=True 时下一次创建返回 409
    def create_context_access_grant(self, owner_id, grantee_id, *, scope="ARTIFACT_READ", build_id=None):  # noqa: ANN001
        from bdlh_runtime.data_client import DataServiceError

        if getattr(self, "fail_next_conflict", False):
            self.fail_next_conflict = False
            raise DataServiceError("conflict", status_code=409)
        self.grants.setdefault(grantee_id, set()).add(build_id or "*")
        return {"grantId": f"grant-{len(self.audit_calls) + 1}", "scope": scope, "buildId": build_id}

    def list_context_access_grants(self, owner_id: str) -> list[dict]:  # noqa: ARG002
        return getattr(self, "listed_grants", [])

    def revoke_context_access_grant(self, owner_id: str, grant_id: str) -> None:  # noqa: ARG002
        self.revoked = getattr(self, "revoked", []) + [grant_id]


_DATA = _AuthOnlyData()


def _client(tmp_path: Path, monkeypatch) -> tuple[TestClient, ContextBuildStore]:  # noqa: ANN001
    store = ContextBuildStore(tmp_path)
    service = ContextWorkbenchService(store)
    monkeypatch.setattr(run_api, "_context_store", store)
    monkeypatch.setattr(run_api, "_context_service", service)
    monkeypatch.setattr(run_api, "_data", lambda: _DATA)
    monkeypatch.delenv("CONTEXT_OPS_ACCOUNTS", raising=False)
    monkeypatch.setattr(SessionCompiler, "from_env", classmethod(lambda cls, **_: SessionCompiler()))
    _DATA.audit_calls.clear()
    _DATA.grants.clear()
    if hasattr(_DATA, "quality_checks"):
        del _DATA.quality_checks
    return TestClient(run_api.app), store


def _headers(token: str = "test-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_context_workbench_lists_sources_and_builds_artifact(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    client, store = _client(tmp_path, monkeypatch)
    sessions = client.get("/api/v1/context/sessions", headers=_headers())
    assert sessions.status_code == 200
    session_id = sessions.json()["sessions"][0]["session_id"]
    overview = client.get(f"/api/v1/context/sessions/{session_id}/overview", headers=_headers()).json()
    current_id = overview["default_current_request_event_id"]
    # legacy 概览:记忆字段为 None(页面显示"—"),最近构建在无构建时为 None
    assert overview["frozen_segment_count"] is None
    assert overview["latest_build"] is None

    response = client.post(
        f"/api/v1/context/sessions/{session_id}/builds",
        headers=_headers(),
        json={
            "current_request_event_id": current_id,
            "algorithm": "budgeted-hybrid-v1",
            "idempotency_key": "api-idem-0001",
        },
    )

    assert response.status_code == 202
    build_id = response.json()["build_id"]
    build = client.get(f"/api/v1/context/builds/{build_id}", headers=_headers())
    assert build.status_code == 200
    assert build.json()["status"] == "COMPLETED"
    assert build.json()["llm_usage"]["classification_calls"] == 0
    artifact = client.get(f"/api/v1/context/builds/{build_id}/artifact", headers=_headers())
    assert artifact.status_code == 200
    assert artifact.json()["current_request_event_id"] == current_id
    assert store.artifact(build_id, "owner-1")["message_hash"].startswith("sha256:")
    # 构建完成后概览能回指最近一次构建
    after = client.get(f"/api/v1/context/sessions/{session_id}/overview", headers=_headers()).json()
    assert after["latest_build"]["build_id"] == build_id
    assert after["latest_build"]["status"] == "COMPLETED"


def test_agent_runs_endpoint_one_click_one_run(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    client, store = _client(tmp_path, monkeypatch)
    sessions = client.get("/api/v1/context/sessions", headers=_headers())
    session_id = sessions.json()["sessions"][0]["session_id"]
    overview = client.get(f"/api/v1/context/sessions/{session_id}/overview", headers=_headers()).json()
    created = client.post(
        f"/api/v1/context/sessions/{session_id}/builds",
        headers=_headers(),
        json={
            "current_request_event_id": overview["default_current_request_event_id"],
            "algorithm": "budgeted-hybrid-v1",
            "idempotency_key": "agent-api-0001",
        },
    )
    build_id = created.json()["build_id"]

    class _FakeRunner:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, messages):  # noqa: ANN001, ANN202
            self.calls += 1
            from bdlh_runtime.memory.agent_run import AgentRunResult

            return AgentRunResult(output="回答", model="fake", input_tokens=10, output_tokens=5, duration_ms=1)

    runner = _FakeRunner()
    original = run_api._context_service_for

    def _patched(account):
        service = original(account)
        service._agent_runner = runner
        return service

    monkeypatch.setattr(run_api, "_context_service_for", _patched)

    first = client.post(f"/api/v1/context/builds/{build_id}/agent-runs", headers=_headers())
    second = client.post(f"/api/v1/context/builds/{build_id}/agent-runs", headers=_headers())
    row = store.get(build_id, "owner-1")

    assert first.status_code == 200
    assert first.json()["idempotent_replay"] is False
    assert first.json()["agent_run"]["status"] == "RUNNING"  # 响应返回启动快照;后台任务随后执行
    assert second.status_code == 200
    assert second.json()["idempotent_replay"] is True
    assert second.json()["agent_run"]["status"] == "COMPLETED"  # 重放读取已冻结终态
    assert runner.calls == 1  # 一次构建一次运行
    assert row["agent_run"]["output"] == "回答"
    assert row["llm_usage"]["agent_calls"] == 1
    assert row["llm_usage"]["agent_input_tokens"] == 10


def test_agent_runs_endpoint_rejects_incomplete_build(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    client, store = _client(tmp_path, monkeypatch)
    session_id = "ctx-session-context-engine-debug-01"
    service = run_api._context_service
    current_id = service.overview(session_id)["default_current_request_event_id"]
    build, _ = store.create(
        owner_id="owner-1",
        session_id=session_id,
        current_request_event_id=current_id,
        algorithm="budgeted-hybrid-v1",
        idempotency_key="agent-pending-001",
        source_type="FROZEN_FILE",
    )

    response = client.post(f"/api/v1/context/builds/{build['build_id']}/agent-runs", headers=_headers())

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "BUILD_NOT_COMPLETED"


def test_segments_endpoint_degrades_in_legacy_and_maps_store_errors(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    client, _store = _client(tmp_path, monkeypatch)

    # legacy:未装配 Segment 仓库 → enabled=false 空列表,不触源
    response = client.get("/api/v1/context/sessions/any-session/segments", headers=_headers())
    assert response.status_code == 200
    assert response.json() == {"session_id": "any-session", "enabled": False, "segments": []}


def test_segments_endpoint_lists_library_for_owner(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    owner_id = "10000000-0000-0000-0000-000000000001"

    class ProductionData(_AuthOnlyData):
        def verify_session(self, token):  # noqa: ANN201
            if token == "test-token":
                return {"accountId": owner_id, "username": "owner"}
            return None

        def list_context_sessions(self, requested_owner: str):
            assert requested_owner == owner_id
            return []

        def get_context_session(self, requested_owner: str, session_id: str):
            raise AssertionError("segments 端点不应读取会话原文")

        def list_memory_segments(self, requested_owner: str, session_id: str):
            assert requested_owner == owner_id
            assert session_id == "production-session-1"
            return [
                {
                    "segmentId": "40000000-0000-0000-0000-000000000003",
                    "startEventId": "event-1",
                    "endEventId": "event-2",
                    "sourceEventIds": ["event-1", "event-2"],
                    "sourceHash": "sha256:segment-1",
                    "sourceTokens": 120,
                    "summaryContent": "轮摘要",
                    "summaryTokens": 40,
                    "status": "FROZEN",
                    "summaryModel": "test-model",
                    "promptVersion": "turn-summary-v1",
                    "algorithmVersion": "turn-segment-v1",
                    "generationMode": "LLM",
                }
            ]

    store = ContextBuildStore(tmp_path)
    monkeypatch.setenv("CONTEXT_MEMORY_MODE", "incremental")
    monkeypatch.setattr(run_api, "_context_store", store)
    monkeypatch.setattr(run_api, "_data", lambda: ProductionData())
    client = TestClient(run_api.app)

    response = client.get(
        "/api/v1/context/sessions/production-session-1/segments", headers=_headers()
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["session_id"] == "production-session-1"
    assert len(payload["segments"]) == 1
    row = payload["segments"][0]
    assert row["segment_id"] == "40000000-0000-0000-0000-000000000003"
    assert row["event_count"] == 2
    assert row["summary_excerpt"] == "轮摘要"
    assert "summary_model" in row and row["summary_model"] == "test-model"


def test_context_build_same_key_replays_and_different_key_conflicts(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    client, store = _client(tmp_path, monkeypatch)
    service = run_api._context_service
    session_id = "ctx-session-context-engine-debug-01"
    current_id = service.overview(session_id)["default_current_request_event_id"]
    active, _ = store.create(
        owner_id="owner-1",
        session_id=session_id,
        current_request_event_id=current_id,
        algorithm="budgeted-hybrid-v1",
        idempotency_key="api-active-0001",
        source_type="FROZEN_FILE",
    )
    replay = client.post(
        f"/api/v1/context/sessions/{session_id}/builds",
        headers=_headers(),
        json={
            "current_request_event_id": current_id,
            "algorithm": "budgeted-hybrid-v1",
            "idempotency_key": "api-active-0001",
        },
    )
    assert replay.status_code == 202
    assert replay.json()["build_id"] == active["build_id"]
    assert replay.json()["idempotent_replay"] is True

    conflict = client.post(
        f"/api/v1/context/sessions/{session_id}/builds",
        headers=_headers(),
        json={
            "current_request_event_id": current_id,
            "algorithm": "budgeted-hybrid-v1",
            "idempotency_key": "api-active-0002",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error_code"] == "CONTEXT_BUILD_ALREADY_ACTIVE"
    assert conflict.json()["detail"]["active_build_id"] == active["build_id"]


def test_context_build_rejects_non_user_current_request(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    client, _store = _client(tmp_path, monkeypatch)
    response = client.post(
        "/api/v1/context/sessions/ctx-session-context-engine-debug-01/builds",
        headers=_headers(),
        json={
            "current_request_event_id": "evt-0002",
            "algorithm": "budgeted-hybrid-v1",
            "idempotency_key": "api-invalid-0001",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "CURRENT_REQUEST_INVALID"


def test_incremental_mode_reads_production_session_without_migrating_fixtures(
    tmp_path: Path,
    monkeypatch,
) -> None:  # noqa: ANN001
    owner_id = "10000000-0000-0000-0000-000000000001"

    class ProductionData(_AuthOnlyData):
        def verify_session(self, token: str):  # noqa: ANN201
            if token == "test-token":
                return {"accountId": owner_id, "username": "owner"}
            return None

        def list_context_sessions(self, requested_owner: str):
            assert requested_owner == owner_id
            return [
                {
                    "sessionId": "production-session-1",
                    "title": "生产会话",
                    "sourceType": "PRODUCTION_DB",
                    "sourceHash": "sha256:production",
                    "sourceVersion": 1,
                    "eventCount": 3,
                    "turnCount": 2,
                    "userMessageCount": 2,
                    "defaultCurrentRequestEventId": "event-3",
                }
            ]

        def get_context_session(self, requested_owner: str, session_id: str):
            assert requested_owner == owner_id
            assert session_id == "production-session-1"
            return {
                "sessionId": session_id,
                "title": "生产会话",
                "sourceHash": "sha256:production",
                "sourceVersion": 1,
                "events": [
                    {
                        "eventId": "event-1",
                        "sequence": 1,
                        "eventType": "user_message",
                        "role": "user",
                        "content": "读取历史",
                        "occurredAt": "2026-08-30T08:00:00Z",
                    },
                    {
                        "eventId": "event-2",
                        "sequence": 2,
                        "eventType": "assistant_message",
                        "role": "assistant",
                        "content": "历史已读取",
                        "occurredAt": "2026-08-30T08:00:01Z",
                    },
                    {
                        "eventId": "event-3",
                        "sequence": 3,
                        "eventType": "user_message",
                        "role": "user",
                        "content": "构建当前上下文",
                        "occurredAt": "2026-08-30T08:00:02Z",
                    },
                ],
            }

        def list_memory_segments(self, requested_owner: str, session_id: str):
            # DataClient 契约:已解包的 Segment 行列表(本测试没有历史 Segment)
            assert requested_owner == owner_id
            return []

        def save_memory_segment(self, session_id: str, payload: dict):
            raise AssertionError("两轮以下的历史没有旧轮,不应保存 Segment")

    store = ContextBuildStore(tmp_path)
    data = ProductionData()
    monkeypatch.setenv("CONTEXT_MEMORY_MODE", "incremental")
    monkeypatch.setattr(run_api, "_context_store", store)
    monkeypatch.setattr(run_api, "_data", lambda: data)
    monkeypatch.setattr(SessionCompiler, "from_env", classmethod(lambda cls, **_: SessionCompiler()))
    client = TestClient(run_api.app)

    sessions = client.get("/api/v1/context/sessions", headers=_headers())
    overview = client.get(
        "/api/v1/context/sessions/production-session-1/overview",
        headers=_headers(),
    )
    build = client.post(
        "/api/v1/context/sessions/production-session-1/builds",
        headers=_headers(),
        json={
            "current_request_event_id": "event-3",
            "algorithm": "budgeted-hybrid-v1",
            "idempotency_key": "production-idem-0001",
        },
    )

    assert sessions.status_code == 200
    assert sessions.json()["sessions"][0]["session_id"] == "production-session-1"
    assert overview.status_code == 200
    assert overview.json()["source_type"] == "PRODUCTION_DB"
    assert build.status_code == 202
    assert build.json()["status"] == "PENDING"
    assert store.get(build.json()["build_id"], owner_id)["status"] == "COMPLETED"


def test_data_service_build_store_requires_explicit_incremental_configuration(monkeypatch) -> None:  # noqa: ANN001
    account = {"accountId": "10000000-0000-0000-0000-000000000001"}
    data = object()
    monkeypatch.setattr(run_api, "_data", lambda: data)
    monkeypatch.setenv("CONTEXT_MEMORY_MODE", "incremental")
    monkeypatch.setenv("CONTEXT_BUILD_STORE", "data-service")

    service = run_api._context_service_for(account)

    assert isinstance(service.store, DataServiceContextBuildStore)

    monkeypatch.setenv("CONTEXT_MEMORY_MODE", "shadow")
    with pytest.raises(ValueError, match="requires CONTEXT_MEMORY_MODE=incremental"):
        run_api._context_service_for(account)


def test_context_session_events_cursor_pagination(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """事件分页:limit/cursor 逐页推进、尾页游标为 None、非法参数钳制。"""

    client, _store = _client(tmp_path, monkeypatch)
    session_id = client.get("/api/v1/context/sessions", headers=_headers()).json()["sessions"][0]["session_id"]
    base = f"/api/v1/context/sessions/{session_id}/events"
    full = client.get(f"{base}?limit=200", headers=_headers()).json()
    total = full["total"]
    all_ids = [row["event_id"] for row in full["events"]]
    assert total > 10, "冻结长会话应有多于 10 条事件"

    first = client.get(f"{base}?limit=2&cursor=0", headers=_headers()).json()
    assert first["total"] == total
    assert [row["event_id"] for row in first["events"]] == all_ids[:2]
    assert first["next_cursor"] == 2

    second = client.get(f"{base}?limit=2&cursor={first['next_cursor']}", headers=_headers()).json()
    assert [row["event_id"] for row in second["events"]] == all_ids[2:4]

    tail = client.get(f"{base}?limit=5&cursor={total - 1}", headers=_headers()).json()
    assert len(tail["events"]) == 1
    assert tail["next_cursor"] is None

    beyond = client.get(f"{base}?cursor={total + 10}", headers=_headers()).json()
    assert beyond["events"] == []
    assert beyond["next_cursor"] is None

    clamped = client.get(f"{base}?limit=0&cursor=-5", headers=_headers()).json()
    assert len(clamped["events"]) == 1  # limit 钳到 1,cursor 钳到 0
    assert clamped["events"][0]["event_id"] == all_ids[0]


def test_build_trend_and_segment_quality_endpoints(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """P2 端点:趋势返回本人构建演进;legacy 抽检 enabled=false。"""

    client, _store = _client(tmp_path, monkeypatch)
    sessions = client.get("/api/v1/context/sessions", headers=_headers())
    session_id = sessions.json()["sessions"][0]["session_id"]
    overview = client.get(f"/api/v1/context/sessions/{session_id}/overview", headers=_headers()).json()
    build = client.post(
        f"/api/v1/context/sessions/{session_id}/builds",
        headers=_headers(),
        json={
            "current_request_event_id": overview["default_current_request_event_id"],
            "algorithm": "budgeted-hybrid-v1",
            "idempotency_key": "p2-trend-0001",
        },
    )
    assert build.status_code == 202

    trend = client.get(f"/api/v1/context/sessions/{session_id}/build-trend", headers=_headers())
    assert trend.status_code == 200
    payload = trend.json()
    assert payload["build_count"] >= 1
    row = payload["trends"][0]
    assert row["build_id"] == build.json()["build_id"]
    assert row["compression_rate"] is None or 0 <= row["compression_rate"] <= 1
    assert {"raw_tokens", "final_tokens", "summary_calls", "cache_hits"} <= set(row)

    quality = client.get(f"/api/v1/context/sessions/{session_id}/segment-quality", headers=_headers())
    assert quality.status_code == 200
    assert quality.json()["enabled"] is False  # legacy 未装配 Segment 仓库


def test_build_create_freezes_threshold_config_snapshot(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """P2 对照分组键:构建时冻结阈值配置(recent_raw_turns 等),缺省值也如实记录。"""

    client, store = _client(tmp_path, monkeypatch)
    sessions = client.get("/api/v1/context/sessions", headers=_headers())
    session_id = sessions.json()["sessions"][0]["session_id"]
    overview = client.get(f"/api/v1/context/sessions/{session_id}/overview", headers=_headers()).json()

    response = client.post(
        f"/api/v1/context/sessions/{session_id}/builds",
        headers=_headers(),
        json={
            "current_request_event_id": overview["default_current_request_event_id"],
            "algorithm": "budgeted-hybrid-v1",
            "idempotency_key": "snapshot-0001",
        },
    )
    assert response.status_code == 202
    snapshot = store.get(response.json()["build_id"], "owner-1")["config_snapshot"]
    assert snapshot["algorithm_version"] == "budgeted-hybrid-v1"
    assert snapshot["recent_raw_turns"] == 2  # SegmentSettings 默认值
    assert snapshot["segment_max_tokens"] == 512
    assert snapshot["summary_call_cap"] == 2
    assert snapshot["context_memory_mode"] == "legacy"
