from fastapi.testclient import TestClient

from stockwise_analysis.api.routes import create_api_app
from stockwise_analysis.config import Settings
from stockwise_analysis.runtimes.langgraph.graphs.root_graph import build_root_graph
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


def test_get_run_with_explicit_thread_id_after_api_store_is_recreated():
    """run_id 与 thread_id 不同时也必须能定位 Checkpointer 状态。"""
    application = create_application(Settings(environment="development"))
    first_app = create_api_app(application)
    created = TestClient(first_app).post(
        "/api/v1/agent-runs",
        json={"message": "什么是市盈率？", "thread_id": "conversation-001"},
    )
    assert created.status_code == 200
    run_id = created.json()["run_id"]
    assert created.json()["thread_id"] == "conversation-001"

    # 新 API 实例没有旧的 InMemoryRunStore，必须通过 RunRegistry 找到 thread_id。
    second_app = create_api_app(application)
    fetched = TestClient(second_app).get(f"/api/v1/agent-runs/{run_id}")

    assert fetched.status_code == 200
    assert fetched.json()["run_id"] == run_id
    assert fetched.json()["thread_id"] == "conversation-001"


def test_resume_uses_registered_explicit_thread_id():
    """恢复 interrupt 时必须回到创建运行时使用的 LangGraph thread。"""
    application = create_application(Settings(environment="development"))
    application.graph = build_root_graph()
    created = TestClient(create_api_app(application)).post(
        "/api/v1/agent-runs",
        json={"message": "请做技术分析", "thread_id": "conversation-resume"},
    )

    assert created.status_code == 200
    assert created.json()["status"] == "WAITING_USER"
    run_id = created.json()["run_id"]

    # 使用新的 API 实例，确保不能依赖旧实例的运行快照缓存。
    resumed = TestClient(create_api_app(application)).post(
        f"/api/v1/agent-runs/{run_id}/resume",
        json={"value": {"symbol": "600000"}},
    )

    assert resumed.status_code == 200
    assert resumed.json()["thread_id"] == "conversation-resume"
    assert resumed.json()["status"] in {"SUCCESS", "PARTIAL", "LIMITED"}


def test_each_run_reads_its_own_checkpoint_in_a_shared_thread():
    """同一会话产生多个 run 后，旧 run 不得被最新 checkpoint 覆盖。"""
    application = create_application(Settings(environment="development"))
    application.graph = build_root_graph()
    client = TestClient(create_api_app(application))
    first = client.post(
        "/api/v1/agent-runs",
        json={"message": "什么是市盈率？", "thread_id": "conversation-shared"},
    )
    second = client.post(
        "/api/v1/agent-runs",
        json={"message": "什么是市净率？", "thread_id": "conversation-shared"},
    )

    assert first.status_code == second.status_code == 200

    # 重建 API 实例，强制从 Checkpointer + RunRegistry 查询而不是命中本地快照。
    recreated = TestClient(create_api_app(application))
    fetched_first = recreated.get(f"/api/v1/agent-runs/{first.json()['run_id']}")
    fetched_second = recreated.get(f"/api/v1/agent-runs/{second.json()['run_id']}")

    assert fetched_first.status_code == fetched_second.status_code == 200
    first_completed = [e for e in fetched_first.json()["events"] if e["event_type"] == "response.completed"]
    second_completed = [e for e in fetched_second.json()["events"] if e["event_type"] == "response.completed"]
    assert first_completed[-1]["run_id"] == first.json()["run_id"]
    assert second_completed[-1]["run_id"] == second.json()["run_id"]
