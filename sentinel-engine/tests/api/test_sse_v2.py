"""SSE 契约 v2：真流式 token、tool.step、三态终帧（WO-T3-1）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from bdlh_runtime.api.routes import create_api_app
from bdlh_runtime.api.sse import encode_token, encode_tool_step
from bdlh_runtime.cognitive.contracts import CognitiveExecution, CognitiveState, InputEvent, PublicResponse
from bdlh_runtime.config import Settings
from bdlh_runtime.engine.loader import ToolLoader
from bdlh_runtime.engine.loop import AgentLoop
from bdlh_runtime.engine.runtime import EngineRuntime
from bdlh_runtime.tools.catalog import catalog_from_snapshot
from bdlh_runtime.tools.search import SEARCH_TOOLS_NAME
from tests.engine.test_loop import FakeChatModel, _quote_call
from tests.helpers_application import IsolatedChatModel, build_isolated_application
from tests.helpers_direct_response import DeterministicDirectResponseModel
from tests.helpers_encoder import LexicalEncoder
from tests.helpers_registry import seeded_snapshot

SECRET = "test-jwt-secret-with-at-least-thirty-two-bytes"


def _token(user_id: int) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )


def _events(response) -> list[dict]:
    return [json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: ")]


def _types(events: list[dict]) -> list[str]:
    return [event.get("type") for event in events]


class UnevenStreamModel(IsolatedChatModel):
    """故意产出非 24 字定长的 astream 分片。"""

    PIECES = ("你好", "世界，这是", "非均质分片。")

    async def ainvoke(self, messages, **kwargs):
        del messages, kwargs
        return AIMessage(content="".join(self.PIECES))

    async def astream(self, messages, **kwargs):
        del messages, kwargs
        for piece in self.PIECES:
            yield AIMessage(content=piece)


class ClarifyingCognitive:
    async def run(self, event: InputEvent, *, observer: Any = None, checkpoint: Any = None) -> CognitiveExecution:
        del observer, checkpoint
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


class BlockedCognitive:
    async def run(self, event: InputEvent, *, observer: Any = None, checkpoint: Any = None) -> CognitiveExecution:
        del observer, checkpoint
        return CognitiveExecution(
            state=CognitiveState(event=event, public_events=["guardrail.blocked"]),
            response=PublicResponse(
                response_kind="BLOCKED",
                response_structure="SAFETY_BLOCK",
                message="该请求被策略拦截。",
                audit_codes=["DEEP_RESEARCH_NOT_AUTHORIZED"],
                rule_ids=["PLAN-RESEARCH-DEEP-001"],
            ),
        )


class DegradedCognitive:
    async def run(self, event: InputEvent, *, observer: Any = None, checkpoint: Any = None) -> CognitiveExecution:
        del observer, checkpoint
        return CognitiveExecution(
            state=CognitiveState(event=event),
            response=PublicResponse(
                response_kind="LIMITED",
                response_structure="KNOWLEDGE",
                message="当前对话能力暂不可用，请稍后重试。",
                audit_codes=["LLM_UNAVAILABLE"],
            ),
        )


async def _echo(name: str, arguments: dict) -> dict:
    return {"tool": name, "args": arguments}


def _client(*, cognitive: Any | None = None, chat_model: Any | None = None) -> TestClient:
    application = build_isolated_application(
        settings=Settings(auth_required=True, jwt_secret=SECRET),
        cognitive_application=cognitive,
        chat_model=chat_model,
    )
    return TestClient(create_api_app(application))


def test_encode_helpers_emit_named_frames() -> None:
    token = encode_token("你好")
    assert "event: message" in token
    assert '"type": "token"' in token
    step = encode_tool_step(tool="search_tools", arguments={"query": "行情"}, status="pending")
    assert '"type": "tool.step"' in step
    assert '"tool": "search_tools"' in step


def test_tokens_are_not_fixed_24_char_slices() -> None:
    catalog = catalog_from_snapshot(seeded_snapshot())
    runtime = EngineRuntime(
        AgentLoop(
            llm=UnevenStreamModel(DeterministicDirectResponseModel()),
            catalog=catalog,
            executor=_echo,
        )
    )
    client = _client(cognitive=runtime)
    events = _events(
        client.post(
            "/api/v1/chat/stream",
            headers={"Authorization": f"Bearer {_token(7)}"},
            json={"message": "找出最近一个月半导体板块涨幅最高的五家"},
        )
    )
    tokens = [event["content"] for event in events if event.get("type") == "token"]
    assert tokens == list(UnevenStreamModel.PIECES)
    assert not all(len(item) == 24 for item in tokens)
    assert events[0]["type"] == "agent_run"
    assert events[-1]["type"] == "done"
    assert events[-1]["status"] == "COMPLETED"


def test_tool_step_includes_search_tools_and_followup() -> None:
    catalog = catalog_from_snapshot(seeded_snapshot())
    llm = FakeChatModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": SEARCH_TOOLS_NAME,
                        "args": {"query": "实时行情"},
                        "id": "call-search",
                        "type": "tool_call",
                    }
                ],
            ),
            _quote_call(),
            AIMessage(content="宁德时代最新价已从行情工具取得。"),
        ]
    )
    runtime = EngineRuntime(
        AgentLoop(
            llm=llm,
            catalog=catalog,
            executor=_echo,
            loader=ToolLoader(catalog, tool_loading="search", encoder=LexicalEncoder()),
        )
    )
    client = _client(cognitive=runtime)
    events = _events(
        client.post(
            "/api/v1/chat/stream",
            headers={"Authorization": f"Bearer {_token(7)}"},
            json={"message": "找出最近一个月半导体板块涨幅最高的五家"},
        )
    )
    steps = [event for event in events if event.get("type") == "tool.step"]
    tools = [event["tool"] for event in steps]
    assert SEARCH_TOOLS_NAME in tools
    assert "market.get_realtime_quote" in tools
    search_done = next(
        event for event in steps if event["tool"] == SEARCH_TOOLS_NAME and event["status"] != "pending"
    )
    assert search_done.get("query") == "实时行情"
    assert "hitCount" in search_done
    statuses = [event["status"] for event in steps if event["tool"] == SEARCH_TOOLS_NAME]
    assert statuses[0] == "pending"
    assert events[0]["type"] == "agent_run"
    assert events[-1]["type"] == "done"


def test_need_clarification_sequence() -> None:
    events = _events(
        _client(cognitive=ClarifyingCognitive()).post(
            "/api/v1/chat/stream",
            headers={"Authorization": f"Bearer {_token(7)}"},
            json={"message": "请做技术分析"},
        )
    )
    assert events[0]["type"] == "agent_run"
    assert "clarification" in _types(events)
    assert events[-2]["type"] == "response.final"
    assert events[-1]["type"] == "done"
    assert events[-1]["status"] == "NEED_CLARIFICATION"


def test_blocked_sequence_is_failed_without_fake_slices() -> None:
    events = _events(
        _client(cognitive=BlockedCognitive()).post(
            "/api/v1/chat/stream",
            headers={"Authorization": f"Bearer {_token(7)}"},
            json={"message": "请做深度调研"},
        )
    )
    assert events[0]["type"] == "agent_run"
    assert "guardrail.blocked" in _types(events)
    assert events[-1]["status"] == "FAILED"
    tokens = [event for event in events if event.get("type") == "token"]
    assert not any(len(event.get("content") or "") == 24 for event in tokens)


def test_degraded_sequence_marks_limited() -> None:
    events = _events(
        _client(cognitive=DegradedCognitive()).post(
            "/api/v1/chat/stream",
            headers={"Authorization": f"Bearer {_token(7)}"},
            json={"message": "找出最近一个月半导体板块涨幅最高的五家"},
        )
    )
    assert events[0]["type"] == "agent_run"
    assert any(event.get("type") == "status" and event.get("step") == "degraded" for event in events)
    assert events[-2]["type"] == "response.final"
    assert events[-1]["type"] == "done"
    assert events[-1]["status"] == "COMPLETED"
    assert events[-1]["resultStatus"] == "LIMITED"
    tokens = [event["content"] for event in events if event.get("type") == "token"]
    assert tokens
    assert not all(len(item) == 24 for item in tokens)
