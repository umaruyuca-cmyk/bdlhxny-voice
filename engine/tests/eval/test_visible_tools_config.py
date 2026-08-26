"""GT-4:/api/v1/tools 目录代理。

工具范围由模板 tool_delivery 与排除项决定;此端点是目录元数据
(高风险红点/写操作标记)的只读投影。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import bdlh_runtime.run_api as run_api
from tests.eval.test_run_api import FakeDataClient, _auth


@pytest.fixture()
def fake_data(monkeypatch: pytest.MonkeyPatch) -> FakeDataClient:
    data = FakeDataClient()
    monkeypatch.setattr(run_api, "_data", lambda: data)
    return data


@pytest.fixture()
def client(fake_data: FakeDataClient) -> TestClient:
    return TestClient(run_api.app)


def test_tools_endpoint_requires_login(client: TestClient) -> None:
    assert client.get("/api/v1/tools").status_code == 401


def test_tools_endpoint_proxies_catalog(client: TestClient) -> None:
    response = client.get("/api/v1/tools", headers=_auth())
    assert response.status_code == 200
    tools = response.json()
    names = [tool["name"] for tool in tools]
    assert "market.get_realtime_quote" in names
    for tool in tools:
        assert set(tool) == {"name", "description", "domain", "enabled", "side_effect", "risk_level"}
        assert tool["enabled"] is True
        assert tool["side_effect"] == "none"
        assert tool["risk_level"] == "low"
