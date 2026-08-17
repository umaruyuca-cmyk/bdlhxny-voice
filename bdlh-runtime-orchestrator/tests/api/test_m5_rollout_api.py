from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any

import jwt
from fastapi.testclient import TestClient

from bdlh_runtime.api.routes import create_api_app
from bdlh_runtime.cognitive.contracts import (
    CognitiveState,
    InputEvent,
    PublicResponse,
)
from bdlh_runtime.cognitive.orchestrator import CognitiveExecution
from bdlh_runtime.config import Settings
from bdlh_runtime.runtime.application import create_application
from bdlh_runtime.runtime.rollout import (
    CognitiveTrafficRouter,
    RolloutConfig,
    RolloutMode,
    RuntimePath,
    approved_test_gate,
)


SECRET = "test-jwt-secret-with-at-least-thirty-two-bytes"


def _headers(user_id: int = 7) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _events(response: Any) -> list[dict[str, Any]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


class SuccessfulCognitive:
    async def run(self, event: InputEvent, *, observer: Any = None) -> CognitiveExecution:
        del observer
        return CognitiveExecution(
            state=CognitiveState(event=event),
            response=PublicResponse(
                response_kind="ANSWER",
                response_structure="KNOWLEDGE",
                message="新路径回答",
                audit_codes=["M5_TEST"],
            ),
        )


class ClarifyingCognitive:
    async def run(self, event: InputEvent, *, observer: Any = None) -> CognitiveExecution:
        del observer
        message = "请补充标的" if "分析" in event.message else "已收到补充"
        kind = "ASK_USER" if "分析" in event.message else "ANSWER"
        return CognitiveExecution(
            state=CognitiveState(event=event),
            response=PublicResponse(
                response_kind=kind,  # type: ignore[arg-type]
                response_structure="CLARIFICATION" if kind == "ASK_USER" else "KNOWLEDGE",
                message=message,
                next_steps=["请提供名称或代码"] if kind == "ASK_USER" else [],
                audit_codes=["M5_CLARIFY"],
            ),
        )


class FailingCognitive:
    def __init__(self, *, after_domain_request: bool) -> None:
        self.after_domain_request = after_domain_request

    async def run(self, event: InputEvent, *, observer: Any = None) -> CognitiveExecution:
        del event
        if self.after_domain_request:
            observer.on_domain_request(object())
        raise RuntimeError("injected failure")


class GraphSpy:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.ainvoke_calls = 0

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        self.ainvoke_calls += 1
        return await self.inner.ainvoke(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def _application(cognitive: Any):
    application = create_application(Settings(
        environment="development",
        auth_required=True,
        jwt_secret=SECRET,
    ))
    application.traffic_router = CognitiveTrafficRouter(RolloutConfig(
        mode=RolloutMode.ALL,
        gate=approved_test_gate(),
    ))
    application.cognitive_application = cognitive
    application.graph = GraphSpy(application.graph)
    return application


def test_chat_and_agent_run_use_the_same_cognitive_rollout_path() -> None:
    application = _application(SuccessfulCognitive())
    client = TestClient(create_api_app(application))

    chat = client.post(
        "/api/v1/chat/stream",
        headers=_headers(),
        json={"message": "什么是市盈率"},
    )
    run = client.post(
        "/api/v1/agent-runs",
        headers=_headers(),
        json={"message": "什么是市盈率", "thread_id": "same-entry-policy"},
    )

    chat_events = _events(chat)
    assert chat_events[0]["runtimePath"] == RuntimePath.COGNITIVE.value
    assert chat_events[-1]["runtimePath"] == RuntimePath.COGNITIVE.value
    assert run.json()["final_response"]["message"] == "新路径回答"
    run_id = run.json()["run_id"]
    fetched = client.get(f"/api/v1/agent-runs/{run_id}", headers=_headers())
    resumed = client.post(
        f"/api/v1/agent-runs/{run_id}/resume",
        headers=_headers(),
        json={"value": {"message": "继续解释"}},
    )
    assert fetched.status_code == 200
    assert fetched.json()["final_response"]["message"] == "新路径回答"
    assert resumed.status_code == 200
    assert resumed.json()["final_response"]["message"] == "新路径回答"
    assert application.graph.ainvoke_calls == 0


def test_pre_domain_failure_falls_back_to_legacy_once() -> None:
    application = _application(FailingCognitive(after_domain_request=False))
    client = TestClient(create_api_app(application))

    response = client.post(
        "/api/v1/agent-runs",
        headers=_headers(),
        json={"message": "什么是市盈率"},
    )

    assert response.status_code == 200
    assert application.graph.ainvoke_calls == 1
    metrics = application.rollout_metrics.snapshot()
    assert metrics["automatic_fallback:cognitive_finance"] == 1


def test_post_domain_failure_never_replays_on_legacy_path() -> None:
    application = _application(FailingCognitive(after_domain_request=True))
    client = TestClient(create_api_app(application))

    response = client.post(
        "/api/v1/agent-runs",
        headers=_headers(),
        json={"message": "分析贵州茅台"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "FAILED"
    assert response.json()["final_response"]["audit_codes"] == [
        "COGNITIVE_EXECUTION_FAILED_AFTER_SIDE_EFFECT"
    ]
    assert application.graph.ainvoke_calls == 0


def test_cognitive_chat_clarification_keeps_the_same_run_and_path() -> None:
    application = _application(ClarifyingCognitive())
    client = TestClient(create_api_app(application))
    first = client.post(
        "/api/v1/chat/stream",
        headers=_headers(),
        json={"message": "请分析"},
    )
    first_events = _events(first)
    first_run = first_events[0]["runId"]
    session_id = first_events[0]["sessionId"]

    resumed = client.post(
        "/api/v1/chat/stream",
        headers=_headers(),
        json={"sessionId": session_id, "message": "贵州茅台"},
    )
    resumed_events = _events(resumed)

    assert first_events[-1]["status"] == "NEED_CLARIFICATION"
    assert resumed_events[0]["runId"] == first_run
    assert resumed_events[0]["runtimePath"] == RuntimePath.COGNITIVE.value
    assert resumed_events[-1]["status"] == "COMPLETED"
    assert application.graph.ainvoke_calls == 0
