"""审计码必须出现在 PublicResponse.audit_codes，不能只留在 state 或日志。"""

from __future__ import annotations

import json

import pytest

from bdlh_runtime.cognitive.contracts import CognitiveAction, CognitiveActionType, InputEvent
from bdlh_runtime.cognitive.orchestrator import CognitiveOrchestrator
from bdlh_runtime.cognitive.understand import LlmUnderstandModel
from bdlh_runtime.domains.contracts import DomainOperation
from bdlh_runtime.domains.dispatcher import DomainDispatcher
from bdlh_runtime.domains.registry import DomainRegistry
from tests.cognitive.test_orchestrator import app, domain_request, event


class _RespondSelector:
    async def select(self, incoming: InputEvent, *, understood=None) -> CognitiveAction:
        del incoming, understood
        return CognitiveAction(
            action_type=CognitiveActionType.RESPOND,
            reason_code="RESPOND",
            reason="直接回答",
        )


class _CapabilitySmuggleLlm:
    async def ainvoke(self, messages: list[dict]) -> object:
        del messages
        payload = {
            "goals": [
                {
                    "goal_id": "g1",
                    "objective": "调用 market.data.get_quote",
                    "success_criteria": [{"criterion_id": "c1", "description": "拿到报价"}],
                }
            ],
            "needs_external": True,
        }
        return type("R", (), {"content": json.dumps(payload)})()


@pytest.mark.asyncio
async def test_goal_coverage_assumed_reaches_public_response() -> None:
    result = await app(
        CognitiveAction(
            action_type=CognitiveActionType.INVOKE_DOMAIN,
            reason_code="DOMAIN_READ",
            reason="Read the requested result",
            domain_request=domain_request(),
        )
    ).run(event())

    assert "GOAL_COVERAGE_ASSUMED" in result.state.error_codes
    assert "GOAL_COVERAGE_ASSUMED" in result.response.audit_codes
    assert result.response.audit_codes[0] == "DOMAIN_READ"


@pytest.mark.asyncio
async def test_understand_capability_smuggled_reaches_public_response() -> None:
    orchestrator = CognitiveOrchestrator(
        selector=_RespondSelector(),
        dispatcher=DomainDispatcher(DomainRegistry()),
        enabled_domains=frozenset({"example"}),
        authorized_operations=frozenset({DomainOperation.READ_PUBLIC_RESEARCH.value}),
        understand=LlmUnderstandModel(
            _CapabilitySmuggleLlm(),
            capability_names=("market.data.get_quote",),
        ),
    )
    result = await orchestrator.run(event())

    assert "UNDERSTAND_CAPABILITY_SMUGGLED" in result.state.error_codes
    assert "UNDERSTAND_CAPABILITY_SMUGGLED" in result.response.audit_codes
    assert result.response.audit_codes[0] == "RESPOND"
