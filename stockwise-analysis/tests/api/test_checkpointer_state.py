from fastapi.testclient import TestClient

from stockwise_analysis.api.routes import create_api_app
from stockwise_analysis.config import Settings
from stockwise_analysis.runtime.application import create_application


def test_get_run_reads_from_checkpointer_after_api_store_is_recreated():
    application = create_application(Settings(environment="development"))
    first_app = create_api_app(application)
    created = TestClient(first_app).post(
        "/api/v1/agent-runs",
        json={"message": "分析 600000", "symbol": "600000"},
    )
    assert created.status_code == 200
    run_id = created.json()["run_id"]

    # 新 API 实例没有旧的 InMemoryRunStore，但复用同一个 Graph/Checkpointer。
    second_app = create_api_app(application)
    fetched = TestClient(second_app).get(f"/api/v1/agent-runs/{run_id}")

    assert fetched.status_code == 200
    assert fetched.json()["run_id"] == run_id
