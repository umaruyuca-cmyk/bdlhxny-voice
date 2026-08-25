"""Cognitive agent-run 状态查询与恢复（不再依赖 Root Graph Checkpointer）。"""

from typing import Any

from fastapi.testclient import TestClient

from bdlh_runtime.api.routes import create_api_app
from bdlh_runtime.cognitive.contracts import (
    CognitiveExecution,
    CognitiveState,
    InputEvent,
    PublicResponse,
)
from bdlh_runtime.config import Settings
from bdlh_runtime.infra.runtime_path import COGNITIVE_RUNTIME_PATH
from tests.helpers_application import build_isolated_application


class ScriptedCognitive:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, event: InputEvent, *, observer: Any = None, checkpoint: Any = None) -> CognitiveExecution:
        del observer, checkpoint
        self.calls += 1
        asking = self.calls == 1 and "分析" in event.message
        return CognitiveExecution(
            state=CognitiveState(event=event),
            response=PublicResponse(
                response_kind="ASK_USER" if asking else "ANSWER",
                response_structure="CLARIFICATION" if asking else "KNOWLEDGE",
                message="请补充标的" if asking else f"已回答：{event.message}",
                next_steps=["请提供代码"] if asking else [],
                audit_codes=["TEST_RUN"],
            ),
        )


def _application() -> Any:
    return build_isolated_application(
        settings=Settings(auth_required=False),
        engine_runtime=ScriptedCognitive(),
    )


def test_get_run_reads_cognitive_state_from_api_store():
    application = _application()
    client = TestClient(create_api_app(application))
    created = client.post(
        "/api/v1/agent-runs",
        json={"message": "什么是市盈率？"},
    )
    assert created.status_code == 200
    run_id = created.json()["run_id"]
    assert created.json()["final_response"]["message"].startswith("已回答")

    fetched = client.get(f"/api/v1/agent-runs/{run_id}")
    assert fetched.status_code == 200
    assert fetched.json()["run_id"] == run_id
    assert created.json()["events"][0]["runtime_path"] == COGNITIVE_RUNTIME_PATH


def test_get_run_with_explicit_thread_id():
    application = _application()
    client = TestClient(create_api_app(application))
    created = client.post(
        "/api/v1/agent-runs",
        json={"message": "什么是市盈率？", "thread_id": "conversation-001"},
    )
    assert created.status_code == 200
    run_id = created.json()["run_id"]
    assert created.json()["thread_id"] == "conversation-001"

    fetched = client.get(f"/api/v1/agent-runs/{run_id}")
    assert fetched.status_code == 200
    assert fetched.json()["run_id"] == run_id
    assert fetched.json()["thread_id"] == "conversation-001"


def test_resume_uses_registered_cognitive_thread():
    application = _application()
    client = TestClient(create_api_app(application))
    created = client.post(
        "/api/v1/agent-runs",
        json={"message": "请做技术分析", "thread_id": "conversation-resume"},
    )

    assert created.status_code == 200
    assert created.json()["status"] == "WAITING_USER"
    run_id = created.json()["run_id"]

    resumed = client.post(
        f"/api/v1/agent-runs/{run_id}/resume",
        json={"value": {"symbol": "600000"}},
    )

    assert resumed.status_code == 200
    assert resumed.json()["thread_id"] == "conversation-resume"
    assert resumed.json()["status"] == "SUCCESS"


def test_each_run_keeps_its_own_cognitive_state_in_a_shared_thread():
    application = _application()
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

    fetched_first = client.get(f"/api/v1/agent-runs/{first.json()['run_id']}")
    fetched_second = client.get(f"/api/v1/agent-runs/{second.json()['run_id']}")

    assert fetched_first.status_code == fetched_second.status_code == 200
    first_completed = [e for e in fetched_first.json()["events"] if e["event_type"] == "response.completed"]
    second_completed = [e for e in fetched_second.json()["events"] if e["event_type"] == "response.completed"]
    assert first_completed[-1]["run_id"] == first.json()["run_id"]
    assert second_completed[-1]["run_id"] == second.json()["run_id"]
