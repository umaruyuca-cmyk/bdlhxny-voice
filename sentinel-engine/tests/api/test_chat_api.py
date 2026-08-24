import json
from datetime import UTC, datetime, timedelta
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
from bdlh_runtime.infra.runtime_path import COGNITIVE_RUNTIME_PATH
from tests.helpers_application import build_isolated_application

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


class KnowledgeCognitive:
    async def run(self, event: InputEvent, *, observer: Any = None, checkpoint: Any = None) -> CognitiveExecution:
        del observer, checkpoint
        return CognitiveExecution(
            state=CognitiveState(event=event),
            response=PublicResponse(
                response_kind="ANSWER",
                response_structure="KNOWLEDGE",
                message="市盈率（PE）是股票价格与每股收益的比值。",
                evidence_refs=["kb:pe-ratio"],
                data_times=["2026-08-18T00:00:00Z"],
                limitations=["知识问答不构成投资建议"],
                risk_disclosures=["示例风险披露"],
                audit_codes=["TEST_KNOWLEDGE"],
            ),
        )


class ClarifyingCognitive:
    async def run(self, event: InputEvent, *, observer: Any = None, checkpoint: Any = None) -> CognitiveExecution:
        del observer, checkpoint
        asking = "分析" in event.message and "600000" not in event.message
        return CognitiveExecution(
            state=CognitiveState(event=event),
            response=PublicResponse(
                response_kind="ASK_USER" if asking else "ANSWER",
                response_structure="CLARIFICATION" if asking else "KNOWLEDGE",
                message="你想分析哪只股票？" if asking else "已完成对 600000 的分析。",
                next_steps=["请提供名称或代码"] if asking else [],
                evidence_refs=["clarify:instrument"],
                audit_codes=["TEST_CLARIFY"],
            ),
        )


class BlockedCognitive:
    async def run(self, event: InputEvent, *, observer: Any = None, checkpoint: Any = None) -> CognitiveExecution:
        del observer, checkpoint
        return CognitiveExecution(
            state=CognitiveState(event=event, public_events=["guardrail.blocked"]),
            response=PublicResponse(
                response_kind="BLOCKED",
                response_structure="SAFETY_BLOCK",
                message="该请求被策略拦截。",
                evidence_refs=["policy:deep-research"],
                audit_codes=["DEEP_RESEARCH_NOT_AUTHORIZED"],
                rule_ids=["PLAN-RESEARCH-DEEP-001"],
                risk_disclosures=["拦截不构成许可"],
            ),
        )


def _client(*, cognitive: Any | None = None) -> TestClient:
    application = build_isolated_application(
        settings=Settings(auth_required=True, jwt_secret=SECRET),
        cognitive_application=cognitive,
    )
    return TestClient(create_api_app(application))


def test_chat_stream_allows_guest_and_uses_cognitive_path():
    """缺 Token 走游客对话；带合法 JWT 同样走 Cognitive 主路径。"""
    client = _client(cognitive=KnowledgeCognitive())

    guest = client.post(
        "/api/v1/chat/stream",
        json={"message": "什么是市盈率？"},
    )
    response = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"message": "什么是市盈率？"},
    )
    guest_events = _events(guest)
    events = _events(response)

    assert guest.status_code == 200
    assert guest_events[-1]["type"] == "done"
    assert response.status_code == 200
    assert events[0]["runtimePath"] == COGNITIVE_RUNTIME_PATH
    assert any(event.get("type") == "token" for event in events)
    assert events[-1]["type"] == "done"
    assert events[-1]["status"] == "COMPLETED"
    assert events[-1]["runtimePath"] == COGNITIVE_RUNTIME_PATH


def test_chat_stream_validates_enabled_skill_ids_contract():
    """会话 Skill 开关快照：合法 id 通过，非法/重复 id 显式 422，不再静默丢弃。"""
    client = _client(cognitive=KnowledgeCognitive())

    accepted = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={
            "message": "什么是市盈率？",
            "enabledSkillIds": ["finance.stock-research"],
        },
    )
    assert accepted.status_code == 200
    assert _events(accepted)[-1]["type"] == "done"

    for invalid in (["Finance.StockResearch"], ["finance.stock-research", "finance.stock-research"], [""]):
        rejected = client.post(
            "/api/v1/chat/stream",
            headers=_headers(7),
            json={
                "message": "什么是市盈率？",
                "enabledSkillIds": invalid,
            },
        )
        assert rejected.status_code == 422


def test_chat_clarification_resumes_the_same_cognitive_run():
    """澄清后纯代码回答经 Turn Router resume 同一 run（禁止盲目 sticky 以外的路径）。"""
    client = _client(cognitive=ClarifyingCognitive())
    first = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"message": "请做技术分析"},
    )
    first_events = _events(first)
    first_run = next(event["runId"] for event in first_events if event["type"] == "agent_run")
    session_id = next(event["sessionId"] for event in first_events if event["type"] == "agent_run")

    assert first_events[-1]["status"] == "NEED_CLARIFICATION"
    assert first_events[0]["runtimePath"] == COGNITIVE_RUNTIME_PATH

    resumed = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"sessionId": session_id, "message": "600000"},
    )
    resumed_events = _events(resumed)
    resumed_run = next(event["runId"] for event in resumed_events if event["type"] == "agent_run")

    assert resumed_run == first_run
    assert resumed_events[0].get("turnDecision") == "resume"
    assert resumed_events[0]["runtimePath"] == COGNITIVE_RUNTIME_PATH
    assert resumed_events[-1]["type"] == "done"
    assert resumed_events[-1]["status"] == "COMPLETED"


def test_conversations_are_user_scoped_regenerable_and_deletable():
    client = _client(cognitive=KnowledgeCognitive())
    created = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"message": "什么是市净率？"},
    )
    session_id = next(event["sessionId"] for event in _events(created) if event["type"] == "agent_run")

    regenerated = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={
            "sessionId": session_id,
            "message": "什么是市净率？",
            "regenerate": True,
        },
    )
    own_detail = client.get(f"/api/v1/conversations/{session_id}", headers=_headers(7))
    other_detail = client.get(f"/api/v1/conversations/{session_id}", headers=_headers(8))

    assert regenerated.status_code == 200
    assert [item["role"] for item in own_detail.json()["messages"]] == ["user", "assistant"]
    assert other_detail.status_code == 404
    assert client.get("/api/v1/conversations", headers=_headers(8)).json() == []

    deleted = client.delete(f"/api/v1/conversations/{session_id}", headers=_headers(7))
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/conversations/{session_id}", headers=_headers(7)).status_code == 404


def _response_final(events: list[dict]) -> dict:
    """``done`` 仍是流结束标记；``response.final`` 是紧邻其前的结构化终帧。"""

    assert events[-1]["type"] == "done"
    final = events[-2]
    assert final["type"] == "response.final"
    return final


def test_chat_stream_emits_response_final_on_complete():
    """正常完成：SSE 终帧携带审计码与证据引用；token 仍是纯文本。"""
    client = _client(cognitive=KnowledgeCognitive())
    response = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"message": "什么是市盈率？"},
    )
    events = _events(response)
    final = _response_final(events)

    assert final["audit_codes"] == ["TEST_KNOWLEDGE"]
    assert final["evidence_refs"] == ["kb:pe-ratio"]
    assert final["data_times"] == ["2026-08-18T00:00:00Z"]
    assert final["limitations"] == ["知识问答不构成投资建议"]
    assert final["disclosures"] == ["示例风险披露"]
    assert final["response_kind"] == "ANSWER"
    assert all("evidence_refs" not in event for event in events if event.get("type") == "token")


def test_chat_stream_emits_response_final_on_ask_user():
    """ASK_USER：澄清路径同样在 done 前发出 response.final。"""
    client = _client(cognitive=ClarifyingCognitive())
    response = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"message": "请做技术分析"},
    )
    events = _events(response)
    final = _response_final(events)

    assert events[-1]["status"] == "NEED_CLARIFICATION"
    assert final["response_kind"] == "ASK_USER"
    assert final["audit_codes"] == ["TEST_CLARIFY"]
    assert final["evidence_refs"] == ["clarify:instrument"]
    assert any(event.get("type") == "clarification" for event in events)


def test_chat_stream_emits_response_final_on_blocked():
    """BLOCKED：guardrail.blocked 之后仍发出带审计码与证据的终帧。"""
    client = _client(cognitive=BlockedCognitive())
    response = client.post(
        "/api/v1/chat/stream",
        headers=_headers(7),
        json={"message": "请做深度调研"},
    )
    events = _events(response)
    final = _response_final(events)

    assert events[-1]["status"] == "FAILED"
    assert any(event.get("type") == "guardrail.blocked" for event in events)
    assert final["response_kind"] == "BLOCKED"
    assert final["audit_codes"] == ["DEEP_RESEARCH_NOT_AUTHORIZED"]
    assert final["evidence_refs"] == ["policy:deep-research"]
    assert final["disclosures"] == ["拦截不构成许可"]
