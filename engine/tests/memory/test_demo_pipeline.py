"""系统演示管线与公开只读端点的测试(无登录真实数据展示)。

无 LLM key 时管线诚实跳过;公开端点只暴露系统演示账号的只读数据。
全部使用内存/文件 Store,不触网。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bdlh_runtime.run_api as run_api
from bdlh_runtime.memory import ContextWorkbenchService
from bdlh_runtime.memory.demo import DEMO_OWNER, run_demo_pipeline
from bdlh_runtime.memory.sources import FrozenSessionSource
from bdlh_runtime.memory.store import ContextBuildStore


def test_pipeline_skips_without_llm_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """未配置 LLM_API_KEY:逐会话如实 SKIPPED,不产生任何构建。"""

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    results = run_demo_pipeline(artifacts_dir=str(tmp_path), session_ids=["s1", "s2"])
    assert [row["skipped"] for row in results] == ["LLM_UNAVAILABLE", "LLM_UNAVAILABLE"]
    assert list(tmp_path.glob("*.json")) == []


def test_public_endpoints_expose_demo_builds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """公开只读端点:系统账号的构建可匿名读取;他人构建不暴露。"""

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    store = ContextBuildStore(tmp_path)
    monkeypatch.setattr(run_api, "_context_store", store)
    monkeypatch.setattr(run_api, "_context_service", ContextWorkbenchService(store))
    monkeypatch.setattr(run_api, "_data", lambda: type("X", (), {"verify_session": lambda self, t: None})())

    service = ContextWorkbenchService(store, source=FrozenSessionSource())
    session_id = service.sessions()[0]["session_id"]
    build, _replay = service.store.create(
        owner_id=DEMO_OWNER,
        session_id=session_id,
        current_request_event_id=service.overview(session_id)["default_current_request_event_id"],
        algorithm="budgeted-hybrid-v1",
        idempotency_key="demo-test-0001",
        source_type="FROZEN_FILE",
    )
    service.execute_build(str(build["build_id"]), DEMO_OWNER, mode="incremental")

    client = TestClient(run_api.app)

    overview = client.get("/api/v1/public/context-demo")
    assert overview.status_code == 200
    payload = overview.json()
    assert payload["enabled"] is True
    assert payload["llm_configured"] is False  # 无 key 如实标注
    assert any(row["build_id"] == build["build_id"] for row in payload["builds"])

    detail = client.get(f"/api/v1/public/context-demo/builds/{build['build_id']}")
    assert detail.status_code == 200
    # 属主由 store.get 服务端校验;公开行不含 owner_id(_public 已剥离)

    artifact = client.get(f"/api/v1/public/context-demo/builds/{build['build_id']}/artifact")
    assert artifact.status_code == 200
    assert artifact.json()["messages"]


def test_public_endpoints_do_not_expose_other_owners(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """公开演示端点只读系统账号;其他所有者的构建不可见。"""

    owner = "10000000-0000-0000-0000-000000000009"
    store = ContextBuildStore(tmp_path)
    monkeypatch.setattr(run_api, "_context_store", store)
    monkeypatch.setattr(run_api, "_context_service", ContextWorkbenchService(store))
    monkeypatch.setattr(run_api, "_data", lambda: type("X", (), {"verify_session": lambda self, t: None})())

    service = ContextWorkbenchService(store, source=FrozenSessionSource())
    session_id = service.sessions()[0]["session_id"]
    build, _ = service.store.create(
        owner_id=owner,
        session_id=session_id,
        current_request_event_id=service.overview(session_id)["default_current_request_event_id"],
        algorithm="budgeted-hybrid-v1",
        idempotency_key="demo-other-0001",
        source_type="FROZEN_FILE",
    )
    service.execute_build(str(build["build_id"]), owner, mode="incremental")

    client = TestClient(run_api.app)
    overview = client.get("/api/v1/public/context-demo")
    assert overview.status_code == 200
    assert all(row["build_id"] != build["build_id"] for row in overview.json()["builds"])

    detail = client.get(f"/api/v1/public/context-demo/builds/{build['build_id']}")
    assert detail.status_code in {403, 404}


def test_demo_pipeline_skips_without_llm_and_shows_in_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无 key:管线整体跳过(不伪造数据);端点 llm_configured=False 空态。

    必须显式清理 LLM_API_KEY:同进程中先前测试(如 test_run_api 的 startup
    注入 deploy/.env)会把真实密钥留进 os.environ,不清会导致本测试真实调
    用 LLM。
    """

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    store = ContextBuildStore(tmp_path)
    results = run_demo_pipeline(
        artifacts_dir=str(tmp_path),
        session_ids=["ctx-session-database-deploy-01"],
        store=store,
    )
    assert results[0]["skipped"] == "LLM_UNAVAILABLE"
    assert not list(tmp_path.glob("*.json"))  # 未产生任何构建
