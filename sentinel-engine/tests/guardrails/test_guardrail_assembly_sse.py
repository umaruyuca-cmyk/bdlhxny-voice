"""Guardrail 白名单装配与 chat guardrail.blocked SSE。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient
from tests.helpers_application import build_isolated_application

from bdlh_runtime.api.routes import create_api_app
from bdlh_runtime.config import Settings
from bdlh_runtime.contracts.capability_ids import DEEP_SEARCH_CAPABILITY
from bdlh_runtime.engine.loop import AgentLoop
from bdlh_runtime.engine.runtime import EngineRuntime
from bdlh_runtime.guardrails.assembly import authorized_capabilities_from_registry
from bdlh_runtime.tools.capabilities import CapabilityRegistry, CapabilitySpec

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


def test_authorized_capabilities_exclude_deep_research_by_default() -> None:
    registry = CapabilityRegistry(
        [
            CapabilitySpec(
                name="research.web_search",
                description="web",
                domain="finance",
                adapter="http",
            ),
            CapabilitySpec(
                name=DEEP_SEARCH_CAPABILITY,
                description="deep",
                domain="finance",
                adapter="http",
            ),
        ]
    )
    caps = authorized_capabilities_from_registry(registry, deep_research_enabled=False)
    assert "research.web_search" in caps
    assert DEEP_SEARCH_CAPABILITY not in caps


def test_authorized_capabilities_include_deep_research_when_enabled() -> None:
    registry = CapabilityRegistry(
        [
            CapabilitySpec(
                name="research.web_search",
                description="web",
                domain="finance",
                adapter="http",
            ),
        ]
    )
    caps = authorized_capabilities_from_registry(
        registry,
        deep_research_enabled=True,
        deep_research_infra_ready=True,
    )
    assert DEEP_SEARCH_CAPABILITY in caps
    blocked = authorized_capabilities_from_registry(
        registry,
        deep_research_enabled=True,
        deep_research_infra_ready=False,
    )
    assert DEEP_SEARCH_CAPABILITY not in blocked


def test_application_wires_non_empty_capability_whitelist() -> None:
    application = build_isolated_application(
        settings=Settings(auth_required=True, jwt_secret=SECRET),
    )
    names = {card.name for card in application.cognitive_application.catalog.list()}
    assert names
    assert DEEP_SEARCH_CAPABILITY not in names


def test_chat_emits_guardrail_blocked_for_unauthorized_deep_research() -> None:
    from langchain_core.messages import AIMessage
    from tests.engine.test_loop import FakeChatModel
    from tests.helpers_registry import seeded_snapshot

    from bdlh_runtime.tools.catalog import ToolCatalog, catalog_from_snapshot

    source = catalog_from_snapshot(seeded_snapshot())
    catalog = ToolCatalog()
    for card in source.list():
        if card.name != DEEP_SEARCH_CAPABILITY:
            catalog.register(card)
    llm = FakeChatModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": DEEP_SEARCH_CAPABILITY,
                        "args": {"query": "交叉验证"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="should not answer"),
        ]
    )
    runtime = EngineRuntime(
        AgentLoop(
            llm=llm,
            catalog=catalog,
            executor=lambda name, arguments: {"tool": name, "args": arguments},
        )
    )
    application = build_isolated_application(
        settings=Settings(auth_required=True, jwt_secret=SECRET),
        cognitive_application=runtime,
    )
    client = TestClient(create_api_app(application))
    response = client.post(
        "/api/v1/chat/stream",
        headers={"Authorization": f"Bearer {_token(7)}"},
        json={"message": "请对半导体板块做深度调研并交叉验证"},
    )
    events = _events(response)
    blocked = next(event for event in events if event.get("type") == "guardrail.blocked")
    assert blocked["auditCode"] == "TOOL_NOT_VISIBLE"
    assert events[-1]["status"] == "FAILED"
