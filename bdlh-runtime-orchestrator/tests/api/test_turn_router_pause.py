"""Turn Router + Pause（ADR-014）单测。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi.testclient import TestClient

from bdlh_runtime.api.routes import create_api_app
from bdlh_runtime.cognitive.contracts import CognitiveState, InputEvent, PublicResponse
from bdlh_runtime.cognitive.orchestrator import CognitiveExecution
from bdlh_runtime.config import Settings
from bdlh_runtime.runtime.application import create_application
from bdlh_runtime.runtime.turn_router import ASK_WHICH_PROMPT, TurnDecision, route_turn
from tests.helpers_registry import seeded_snapshot

SECRET = "test-jwt-secret-with-at-least-thirty-two-bytes"


def _token(user_id: int) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )


def _headers(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id)}"}


def _events(response) -> list[dict]:
    return [json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: ")]


class ClarifyingCognitive:
    async def run(self, event: InputEvent, *, observer: Any = None) -> CognitiveExecution:
        del observer
        asking = "分析" in event.message and "600000" not in event.message
        return CognitiveExecution(
            state=CognitiveState(event=event),
            response=PublicResponse(
                response_kind="ASK_USER" if asking else "ANSWER",
                response_structure="CLARIFICATION" if asking else "KNOWLEDGE",
                message="你想分析哪只股票？" if asking else "已完成对 600000 的分析。",
                next_steps=["请提供名称或代码"] if asking else [],
                audit_codes=["TEST_CLARIFY"],
            ),
        )


def _client(*, cognitive: Any | None = None) -> tuple[TestClient, Any]:
    application = create_application(
        Settings(environment="test", auth_required=True, jwt_secret=SECRET),
        registry_snapshot=seeded_snapshot(),
    )
    if cognitive is not None:
        application.cognitive_application = cognitive
    return TestClient(create_api_app(application)), application


def test_route_turn_classifies_resume_new_turn_and_ask_which():
    assert route_turn(message="hi", pending_run_id=None).decision == TurnDecision.FRESH
    assert route_turn(message="600000", pending_run_id="r1").decision == TurnDecision.RESUME
    assert route_turn(message="继续", pending_run_id="r1").decision == TurnDecision.RESUME
    assert route_turn(message="换一个问题", pending_run_id="r1").decision == TurnDecision.NEW_TURN
    ambiguous = route_turn(message="再看看市场情绪", pending_run_id="r1")
    assert ambiguous.decision == TurnDecision.ASK_WHICH
    confirmed = route_turn(message="继续", pending_run_id="r1", awaiting_route_confirm=True)
    assert confirmed.decision == TurnDecision.RESUME


def test_chat_clarification_resumes_same_run_for_symbol_answer():
    client, _ = _client(cognitive=ClarifyingCognitive())
    first = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"message": "请做技术分析", "mode": "general"},
    )
    first_events = _events(first)
    first_run = next(event["runId"] for event in first_events if event["type"] == "agent_run")
    session_id = next(event["sessionId"] for event in first_events if event["type"] == "agent_run")

    resumed = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"sessionId": session_id, "message": "600000", "mode": "general"},
    )
    resumed_events = _events(resumed)
    resumed_run = next(event["runId"] for event in resumed_events if event["type"] == "agent_run")

    assert resumed_run == first_run
    assert resumed_events[0]["turnDecision"] == "resume"
    assert resumed_events[-1]["status"] == "COMPLETED"


def test_chat_pending_ambiguous_message_asks_which_without_main_graph():
    client, application = _client(cognitive=ClarifyingCognitive())
    calls = {"n": 0}
    original = application.cognitive_application

    class Counting:
        async def run(self, event: InputEvent, *, observer: Any = None) -> CognitiveExecution:
            calls["n"] += 1
            return await original.run(event, observer=observer)

    application.cognitive_application = Counting()
    first = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"message": "请做技术分析", "mode": "general"},
    )
    session_id = next(event["sessionId"] for event in _events(first) if event["type"] == "agent_run")
    before = calls["n"]

    confirm = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"sessionId": session_id, "message": "再看看市场情绪怎么样", "mode": "general"},
    )
    events = _events(confirm)
    assert calls["n"] == before
    assert events[0]["turnDecision"] == "ask_which"
    assert events[-1]["status"] == "ROUTE_CONFIRM"
    assert any(ASK_WHICH_PROMPT in (event.get("content") or "") for event in events if event.get("type") == "token")


def test_chat_pending_new_turn_abandons_old_run():
    client, _ = _client(cognitive=ClarifyingCognitive())
    first = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"message": "请做技术分析", "mode": "general"},
    )
    first_events = _events(first)
    first_run = next(event["runId"] for event in first_events if event["type"] == "agent_run")
    session_id = next(event["sessionId"] for event in first_events if event["type"] == "agent_run")

    switched = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"sessionId": session_id, "message": "换一个问题，什么是市盈率", "mode": "general"},
    )
    switched_events = _events(switched)
    new_run = next(event["runId"] for event in switched_events if event["type"] == "agent_run")

    assert new_run != first_run
    assert switched_events[0]["turnDecision"] == "new_turn"


def test_resolve_resume_message_replays_prior_objective():
    from bdlh_runtime.runtime.turn_router import TurnRoute, resolve_resume_message

    route = TurnRoute(decision=TurnDecision.RESUME, reason="STRONG_RESUME", pending_run_id="r1")
    assert (
        resolve_resume_message(
            user_message="继续",
            route=route,
            prior_user_messages=["分析贵州茅台", "继续"],
        )
        == "分析贵州茅台"
    )
    clarify = TurnRoute(decision=TurnDecision.RESUME, reason="CLARIFICATION_ANSWER", pending_run_id="r1")
    assert (
        resolve_resume_message(
            user_message="600519",
            route=clarify,
            prior_user_messages=["分析一下", "600519"],
        )
        == "600519"
    )


class CapturingCognitive:
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def run(self, event: InputEvent, *, observer: Any = None) -> CognitiveExecution:
        del observer
        self.seen.append(event.message)
        if len(self.seen) == 1:
            return CognitiveExecution(
                state=CognitiveState(event=event),
                response=PublicResponse(
                    response_kind="ASK_USER",
                    response_structure="CLARIFICATION",
                    message="你想分析哪只股票？",
                    next_steps=["请提供名称或代码"],
                    audit_codes=["TEST_CLARIFY"],
                ),
            )
        return CognitiveExecution(
            state=CognitiveState(event=event),
            response=PublicResponse(
                response_kind="ANSWER",
                response_structure="KNOWLEDGE",
                message=f"已处理：{event.message}",
                audit_codes=["TEST_ANSWER"],
            ),
        )


def test_chat_continue_restores_prior_objective_message():
    cognitive = CapturingCognitive()
    client, _ = _client(cognitive=cognitive)
    first = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"message": "分析贵州茅台适合我吗"},
    )
    assert first.status_code == 200
    first_events = _events(first)
    session_id = first_events[0]["sessionId"]
    assert first_events[0]["turnDecision"] == "fresh"

    resumed = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"sessionId": session_id, "message": "继续"},
    )
    assert resumed.status_code == 200
    resumed_events = _events(resumed)
    assert resumed_events[0]["turnDecision"] == "resume"
    assert cognitive.seen == ["分析贵州茅台适合我吗", "分析贵州茅台适合我吗"]


def test_pause_endpoint_sets_pending_and_is_resumable():
    client, application = _client(cognitive=ClarifyingCognitive())
    run = client.post(
        "/api/v1/agent-runs",
        headers=_headers(7),
        json={"message": "请做技术分析"},
    )
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "WAITING_USER"
    run_id = body["run_id"]
    thread_id = body["thread_id"]

    paused = client.post(f"/api/v1/agent-runs/{run_id}/pause", headers=_headers(7))
    assert paused.status_code == 200
    ack = paused.json()
    assert ack["runId"] == run_id
    assert ack["status"] == "PAUSED_BY_USER"
    assert ack["resumable"] is True
    assert application.run_control.is_pause_requested(run_id) is True

    session = application.chat_session_store.get(thread_id, "7")
    assert session is not None
    assert session.pending_run_id == run_id
    assert session.pause_reason == "user_pause"


def test_cancel_endpoint_abandons_and_clears_pending():
    client, application = _client(cognitive=ClarifyingCognitive())
    run = client.post(
        "/api/v1/agent-runs",
        headers=_headers(7),
        json={"message": "请做技术分析"},
    )
    assert run.status_code == 200
    run_id = run.json()["run_id"]
    thread_id = run.json()["thread_id"]

    client.post(f"/api/v1/agent-runs/{run_id}/pause", headers=_headers(7))
    cancelled = client.post(f"/api/v1/agent-runs/{run_id}/cancel", headers=_headers(7))
    assert cancelled.status_code == 200
    ack = cancelled.json()
    assert ack["runId"] == run_id
    assert ack["status"] == "ABANDONED"
    assert ack["resumable"] is False

    session = application.chat_session_store.get(thread_id, "7")
    assert session is not None
    assert session.pending_run_id is None

    again = client.post(f"/api/v1/agent-runs/{run_id}/cancel", headers=_headers(7))
    assert again.status_code == 409