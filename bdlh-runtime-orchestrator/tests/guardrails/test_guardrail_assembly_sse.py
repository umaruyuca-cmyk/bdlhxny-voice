"""Guardrail 白名单装配与 chat guardrail.blocked SSE。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi.testclient import TestClient

from bdlh_runtime.api.routes import create_api_app
from bdlh_runtime.cognitive.contracts import CognitiveState, InputEvent, PublicResponse
from bdlh_runtime.cognitive.orchestrator import CognitiveExecution, CognitiveOrchestrator
from tests.helpers_understand import RuleBasedUnderstandModel
from bdlh_runtime.config import Settings
from bdlh_runtime.contracts.capability_ids import DEEP_SEARCH_CAPABILITY
from bdlh_runtime.domains.contracts import DomainBudget, DomainOperation, DomainRequest
from bdlh_runtime.guardrails.assembly import authorized_capabilities_from_registry
from bdlh_runtime.tools.capabilities import CapabilityRegistry, CapabilitySpec
from tests.helpers_application import build_isolated_application

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
    caps = application.cognitive_application._authorized_capabilities
    assert caps
    assert DEEP_SEARCH_CAPABILITY not in caps


class BlockingSelector:
    async def select(self, event: InputEvent, *, understood=None):
        del understood
        from bdlh_runtime.cognitive.contracts import CognitiveAction, CognitiveActionType

        return CognitiveAction(
            action_type=CognitiveActionType.INVOKE_DOMAIN,
            reason_code="DEEP",
            reason="deep",
            domain_request=DomainRequest(
                request_id=f"{event.event_id}:deep",
                domain="finance",
                authenticated_user_id=event.user_id,
                objective="请做深度调研并交叉验证",
                success_criteria=["来源A足够长", "来源B足够长"],
                authorized_operations={DomainOperation.READ_PUBLIC_RESEARCH},
                budget=DomainBudget(tool_call_limit=3, runtime_seconds=30),
            ),
        )


class NoopDispatcher:
    async def dispatch(self, request: object) -> Any:
        raise AssertionError("dispatcher should not be called when plan guardrail blocks")


def test_chat_emits_guardrail_blocked_for_unauthorized_deep_research() -> None:
    application = build_isolated_application(
        settings=Settings(auth_required=True, jwt_secret=SECRET),
        cognitive_application=CognitiveOrchestrator(
            selector=BlockingSelector(),
            dispatcher=NoopDispatcher(),
            enabled_domains=frozenset({"finance"}),
            authorized_operations=frozenset({"READ_PUBLIC_RESEARCH"}),
            authorized_capabilities=frozenset({"research.web_search"}),
            understand=RuleBasedUnderstandModel(),
        ),
    )
    client = TestClient(create_api_app(application))
    response = client.post(
        "/api/v1/chat/stream",
        headers={"Authorization": f"Bearer {_token(7)}"},
        json={"message": "请做深度调研"},
    )
    events = _events(response)
    blocked = next(event for event in events if event.get("type") == "guardrail.blocked")
    assert blocked["auditCode"] == "DEEP_RESEARCH_NOT_AUTHORIZED"
    assert "PLAN-RESEARCH-DEEP-001" in blocked["ruleIds"]
    assert events[-1]["status"] == "FAILED"
