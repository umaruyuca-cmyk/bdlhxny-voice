"""批次过程管理(任务四):取消端点边界。

此处覆盖 /api/v1/jobs 取消端点的边界行为(未知作业 404)。
匿名任务与模板批次的取消路径分别在 experiments/test_public_api 与
experiments/test_jobs 覆盖。
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


def test_cancel_unknown_job_is_404(client, finance_pack):  # noqa: ANN001
    assert client.post("/api/v1/jobs/missing/cancel", headers=_auth()).status_code == 404
