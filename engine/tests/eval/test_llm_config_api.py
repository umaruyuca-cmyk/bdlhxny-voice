"""LLM 配置口径:env 是唯一真源(无账号级可配置模块)。

- GET/PUT /api/v1/llm-config 已删除,返回 404;
- POST /api/v1/llm-config/test 只读探测服务端 env,不接收配置体;
- 发起批次不再读取账号配置,密钥只存在于服务端 env。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import bdlh_runtime.run_api as run_api

SECRET = "sk-live-abcdef123456"


class FakeLlmData:
    """最小 data 面账号配置方法已不存在——若引擎仍调用会 AttributeError,测试即失败。"""

    def verify_session(self, token: str) -> dict[str, Any] | None:
        return {"accountId": "acct-1", "username": "owner"} if token == "t" else None

    def list_cases(self) -> list[dict[str, Any]]:
        # 压缩对照通道只接受带对照变体(full / budgeted-*)的 ctx 用例
        return [
            {
                "id": "ctx-mini-port",
                "variants": [{"variantId": "full"}, {"variantId": "budgeted-hybrid-v1"}],
            }
        ]

    def get_tool_catalog(self) -> dict[str, Any]:
        return {"capabilities": []}

    def create_batch(self, *, name: str, experiment_type: str, fixed_conditions: dict[str, Any]) -> str:
        self.batch_fixed_conditions.append(fixed_conditions)
        return "batch-1"

    batch_fixed_conditions: list[dict[str, Any]] = []

    def complete_batch(self, batch_id: str, status: str) -> None:
        pass


@pytest.fixture()
def fake_data(monkeypatch: pytest.MonkeyPatch) -> FakeLlmData:
    data = FakeLlmData()
    monkeypatch.setattr(run_api, "_data", lambda: data)
    return data


@pytest.fixture()
def client(fake_data: FakeLlmData) -> TestClient:
    return TestClient(run_api.app)


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer t"}


def test_account_config_endpoints_removed(client: TestClient) -> None:
    """账号级 LLM 配置模块已删除:读写端点不存在。"""

    assert client.get("/api/v1/llm-config", headers=_auth()).status_code == 404
    assert (
        client.put(
            "/api/v1/llm-config",
            json={"base_url": "https://api.deepseek.com/v1", "model": "x", "api_key": SECRET},
            headers=_auth(),
        ).status_code
        == 404
    )


def test_probe_endpoint_uses_env_only(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """连通性测试只读 env:配置体即使传入也不改变探测目标。"""

    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.internal/v1")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    monkeypatch.setenv("LLM_API_KEY", SECRET)
    captured: dict[str, Any] = {}

    def fake_probe(base_url: str, model: str, api_key: str) -> tuple[bool, str]:
        captured.update(base_url=base_url, model=model, api_key=api_key)
        return True, "连接成功,模型可用"

    monkeypatch.setattr(run_api, "_probe_llm", fake_probe)
    body = client.post("/api/v1/llm-config/test", headers=_auth()).json()
    assert body["ok"] is True
    assert captured["base_url"] == "https://gateway.example.internal/v1"
    assert captured["model"] == "env-model"
    assert captured["api_key"] == SECRET
    # 携带配置体也不生效:端点无 body 参数,请求体被忽略,仍探测 env
    resp = client.post(
        "/api/v1/llm-config/test",
        json={"base_url": "https://other.example/v1", "model": "other", "api_key": "k"},
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert resp.json()["baseUrl"] == "https://gateway.example.internal/v1"
    assert SECRET not in resp.text


def test_probe_endpoint_reports_missing_env(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    body = client.post("/api/v1/llm-config/test", headers=_auth()).json()
    assert body["ok"] is False
    assert "LLM_API_KEY" in body["error"]

    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    body = client.post("/api/v1/llm-config/test", headers=_auth()).json()
    assert body["ok"] is False
    assert "LLM_BASE_URL" in body["error"] and "唯一真源" in body["error"]


def test_batch_never_reads_account_config(
    client: TestClient, fake_data: FakeLlmData, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """发起批次不触碰账号配置;密钥不进 fixed_conditions(压缩对照通道)。"""

    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setattr(run_api, "ARTIFACTS_DIR", tmp_path)

    def fake_execute(_request: Any, _views: Any, _selected: Any) -> tuple[dict[str, Any], list[Any]]:
        return {"run_records": []}, []

    monkeypatch.setattr(run_api, "_execute_context_eval", fake_execute)
    resp = client.post(
        "/api/v1/context-batches",
        json={"case_ids": ["ctx-mini-port"], "runs": 1},
        headers=_auth(),
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    for _ in range(50):
        job = client.get(f"/api/v1/jobs/{job_id}", headers=_auth()).json()
        if job["status"] != "running":
            break
        import time

        time.sleep(0.02)
    assert job["status"] == "done"
    for fixed in fake_data.batch_fixed_conditions:
        assert SECRET not in str(fixed), "密钥不得进入 fixed_conditions"
