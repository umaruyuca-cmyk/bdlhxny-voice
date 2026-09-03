"""上下文工作台细粒度 RBAC(P1)的 API 测试:脱敏运维视图、下载/复制权限、审计。

全部使用内存 Store 与假数据客户端,不触网、不连库。
复用 test_context_workbench_api 的装配助手(_client/_headers/_DATA)。
"""

from __future__ import annotations

from pathlib import Path

from tests.eval.test_context_workbench_api import _DATA, _client, _headers


def _completed_build(client, monkeypatch, idem: str = "rbac-0001") -> str:  # noqa: ANN001
    sessions = client.get("/api/v1/context/sessions", headers=_headers())
    session_id = sessions.json()["sessions"][0]["session_id"]
    overview = client.get(f"/api/v1/context/sessions/{session_id}/overview", headers=_headers()).json()
    response = client.post(
        f"/api/v1/context/sessions/{session_id}/builds",
        headers=_headers(),
        json={
            "current_request_event_id": overview["default_current_request_event_id"],
            "algorithm": "budgeted-hybrid-v1",
            "idempotency_key": idem,
        },
    )
    assert response.status_code == 202
    return response.json()["build_id"]


def test_artifact_download_audited_for_owner(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    client, _store = _client(tmp_path, monkeypatch)
    build_id = _completed_build(client, monkeypatch)

    response = client.get(f"/api/v1/context/builds/{build_id}/artifact", headers=_headers())

    assert response.status_code == 200
    audits = [row for row in _DATA.audit_calls if row["action"] == "CONTEXT_ARTIFACT_DOWNLOAD"]
    assert len(audits) == 1
    assert audits[0]["detail"]["via"] == "owner"
    assert audits[0]["detail"]["build_id"] == build_id
    # 手动重建审计同样写入(需求 §18.2)
    assert any(row["action"] == "CONTEXT_BUILD_CREATED" for row in _DATA.audit_calls)


def test_artifact_download_rejects_other_owner_without_grant(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    client, _store = _client(tmp_path, monkeypatch)
    build_id = _completed_build(client, monkeypatch)

    response = client.get(f"/api/v1/context/builds/{build_id}/artifact", headers=_headers("other-token"))

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "FORBIDDEN"
    assert not [row for row in _DATA.audit_calls if row["action"] == "CONTEXT_ARTIFACT_DOWNLOAD"]


def test_artifact_download_via_active_grant(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    client, _store = _client(tmp_path, monkeypatch)
    build_id = _completed_build(client, monkeypatch)
    _DATA.grants["owner-2"] = {build_id}

    response = client.get(f"/api/v1/context/builds/{build_id}/artifact", headers=_headers("other-token"))

    assert response.status_code == 200
    audits = [row for row in _DATA.audit_calls if row["action"] == "CONTEXT_ARTIFACT_DOWNLOAD"]
    assert len(audits) == 1
    assert audits[0]["detail"]["via"] == "grant"


def test_copy_audit_requires_content_access(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    client, _store = _client(tmp_path, monkeypatch)
    build_id = _completed_build(client, monkeypatch)

    denied = client.post(
        f"/api/v1/context/builds/{build_id}/access-audit",
        headers=_headers("other-token"),
        json={"action": "CONTEXT_CONTENT_COPY"},
    )
    assert denied.status_code == 403

    _DATA.grants["owner-2"] = {"*"}
    allowed = client.post(
        f"/api/v1/context/builds/{build_id}/access-audit",
        headers=_headers("other-token"),
        json={"action": "CONTEXT_CONTENT_COPY"},
    )
    assert allowed.status_code == 204
    assert any(row["action"] == "CONTEXT_CONTENT_COPY" and row["account_id"] == "owner-2" for row in _DATA.audit_calls)


def test_agent_run_start_audited(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    client, _store = _client(tmp_path, monkeypatch)
    build_id = _completed_build(client, monkeypatch)

    response = client.post(f"/api/v1/context/builds/{build_id}/agent-runs", headers=_headers())

    assert response.status_code == 200
    assert any(row["action"] == "CONTEXT_AGENT_RUN_STARTED" for row in _DATA.audit_calls)


def test_owner_reads_own_audit_trail(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    client, _store = _client(tmp_path, monkeypatch)
    _completed_build(client, monkeypatch)

    response = client.get("/api/v1/context/audit", headers=_headers())

    assert response.status_code == 200
    actions = [row["action"] for row in response.json()["events"]]
    assert "CONTEXT_BUILD_CREATED" in actions
    # 只有自己的事件(假实现按 account_id 过滤)
    assert all(row["accountId"] == "owner-1" for row in response.json()["events"])


def test_grant_management_endpoints(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    client, _store = _client(tmp_path, monkeypatch)

    self_grant = client.post(
        "/api/v1/context/access-grants",
        headers=_headers(),
        json={"grantee_account_id": "owner-1"},
    )
    assert self_grant.status_code == 400
    assert self_grant.json()["detail"]["error_code"] == "GRANT_SELF_FORBIDDEN"

    created = client.post(
        "/api/v1/context/access-grants",
        headers=_headers(),
        json={"grantee_account_id": "20000000-0000-0000-0000-000000000002", "build_id": "ctxb-1"},
    )
    assert created.status_code == 201
    assert created.json()["scope"] == "ARTIFACT_READ"
    assert any(row["action"] == "CONTEXT_GRANT_CREATED" for row in _DATA.audit_calls)

    _DATA.fail_next_conflict = True
    conflict = client.post(
        "/api/v1/context/access-grants",
        headers=_headers(),
        json={"grantee_account_id": "20000000-0000-0000-0000-000000000002", "build_id": "ctxb-1"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error_code"] == "GRANT_ALREADY_ACTIVE"

    revoked = client.delete("/api/v1/context/access-grants/grant-1", headers=_headers())
    assert revoked.status_code == 204
    assert any(row["action"] == "CONTEXT_GRANT_REVOKED" for row in _DATA.audit_calls)


def test_ops_builds_view_requires_ops_account_and_sanitizes(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    client, _store = _client(tmp_path, monkeypatch)
    build_id = _completed_build(client, monkeypatch)

    # 名单为空:任何人(包括普通所有者)都被拒绝
    denied = client.get("/api/v1/context/ops/builds", headers=_headers())
    assert denied.status_code == 403
    assert denied.json()["detail"]["error_code"] == "OPS_FORBIDDEN"

    monkeypatch.setenv("CONTEXT_OPS_ACCOUNTS", "ops-1")
    allowed = client.get("/api/v1/context/ops/builds", headers=_headers("ops-token"))
    assert allowed.status_code == 200
    rows = allowed.json()["builds"]
    assert rows, "应至少列出刚完成的构建"
    row = next(item for item in rows if item["build_id"] == build_id)
    # 脱敏口径:只有状态/计量/错误码;没有消息正文、模型输出与自由文本错误
    assert set(row) == {
        "build_id",
        "session_id",
        "owner_ref",
        "status",
        "current_phase",
        "algorithm_version",
        "error_code",
        "budget",
        "llm_usage",
        "agent_run",
        "created_at",
        "updated_at",
    }
    assert len(row["owner_ref"]) == 12
    assert "owner-1" not in str(row)
    assert "error_message" not in row and "messages" not in row
    assert "total" in allowed.json() and "next_cursor" in allowed.json()


def test_ops_audit_view_hides_account_ids(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    client, _store = _client(tmp_path, monkeypatch)
    _completed_build(client, monkeypatch, idem="rbac-ops-0002")

    monkeypatch.setenv("CONTEXT_OPS_ACCOUNTS", "ops-1")
    response = client.get("/api/v1/context/ops/audit", headers=_headers("ops-token"))

    assert response.status_code == 200
    events = response.json()["events"]
    assert events, "应列出跨所有者审计事件"
    assert all("accountId" not in row and len(row["owner_ref"]) == 12 for row in events)
    assert any(row["action"] == "CONTEXT_BUILD_CREATED" for row in events)
    # 非运维账号依旧 403
    assert client.get("/api/v1/context/ops/audit", headers=_headers()).status_code == 403


def test_ops_account_cannot_read_content_without_grant(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """运维身份只解锁脱敏元数据;读原文仍走所有者/授权判定(需求 §5.3)。"""

    client, _store = _client(tmp_path, monkeypatch)
    build_id = _completed_build(client, monkeypatch)
    monkeypatch.setenv("CONTEXT_OPS_ACCOUNTS", "ops-1")

    response = client.get(f"/api/v1/context/builds/{build_id}/artifact", headers=_headers("ops-token"))

    assert response.status_code == 403
    assert not [row for row in _DATA.audit_calls if row["action"] == "CONTEXT_ARTIFACT_DOWNLOAD"]


def test_manual_analysis_trigger_is_ops_gated(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    client, _store = _client(tmp_path, monkeypatch)

    denied = client.post("/api/v1/context/ops/analysis/run", headers=_headers())
    assert denied.status_code == 403
    assert denied.json()["detail"]["error_code"] == "OPS_FORBIDDEN"

    monkeypatch.setenv("CONTEXT_OPS_ACCOUNTS", "ops-1")
    allowed = client.post("/api/v1/context/ops/analysis/run", headers=_headers("ops-token"))
    assert allowed.status_code == 202
    assert allowed.json()["trigger"] == "MANUAL"
    assert any(row["action"] == "CONTEXT_ANALYSIS_RUN" for row in _DATA.audit_calls)


def test_ops_analysis_list_returns_runs(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    client, _store = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("CONTEXT_OPS_ACCOUNTS", "ops-1")

    denied = client.get("/api/v1/context/ops/analysis", headers=_headers())
    assert denied.status_code == 403

    response = client.get("/api/v1/context/ops/analysis", headers=_headers("ops-token"))
    assert response.status_code == 200
    runs = response.json()["runs"]
    assert runs and runs[0]["run_id"] == "run-1"
    assert set(runs[0]) >= {
        "run_id",
        "status",
        "trigger_source",
        "sampled_segments",
        "judge_calls",
        "judge_errors",
        "report",
        "started_at",
    }


def test_segment_quality_includes_persisted_semantic_checks(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    client, _store = _client(tmp_path, monkeypatch)
    sessions = client.get("/api/v1/context/sessions", headers=_headers())
    session_id = sessions.json()["sessions"][0]["session_id"]
    _DATA.quality_checks = [
        {
            "segmentId": "seg-1",
            "verdict": "FAIL",
            "missingFacts": '["漏了关键约束"]',
            "hallucinations": "[]",
            "judgeModel": "fake-judge",
            "promptVersion": "segment-judge-v1",
            "errorCode": None,
            "createdAt": "2026-08-30T23:00:00+08:00",
        }
    ]

    response = client.get(f"/api/v1/context/sessions/{session_id}/segment-quality", headers=_headers())

    assert response.status_code == 200
    semantic = response.json()["semantic"]
    assert semantic and semantic[0]["segment_id"] == "seg-1"
    assert semantic[0]["verdict"] == "FAIL"
    assert semantic[0]["missing_facts"] == ["漏了关键约束"]
    assert semantic[0]["prompt_version"] == "segment-judge-v1"
