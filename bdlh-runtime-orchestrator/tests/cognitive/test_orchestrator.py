from __future__ import annotations

import pytest

from bdlh_runtime.cognitive.contracts import CognitiveAction, CognitiveActionType, InputEvent
from bdlh_runtime.cognitive.orchestrator import CognitiveOrchestrator
from bdlh_runtime.domains.contracts import (
    ConfidenceAssessment,
    DomainBudget,
    DomainFact,
    DomainOperation,
    DomainOutcome,
    DomainRequest,
)
from bdlh_runtime.domains.dispatcher import DomainDispatcher
from bdlh_runtime.domains.registry import DomainRegistry


class Selector:
    def __init__(self, action: CognitiveAction) -> None:
        self.action = action

    async def select(self, event: InputEvent) -> CognitiveAction:
        return self.action


class Domain:
    async def run(self, request: DomainRequest) -> DomainOutcome:
        return DomainOutcome(
            request_id=request.request_id,
            domain=request.domain,
            status="COMPLETE",
            established_facts=[DomainFact(fact_id="fact-1", statement="validated", source_refs=["source-1"], directness="DIRECT")],
            confidence=ConfidenceAssessment(level="HIGH", reasons=["validated"], coverage_status="COMPLETE"),
        )


def event() -> InputEvent:
    return InputEvent(event_id="event-1", user_id="user-1", session_id="session-1", message="hello")


def domain_request() -> DomainRequest:
    return DomainRequest(
        request_id="request-1",
        domain="example",
        authenticated_user_id="user-1",
        objective="Read a validated result",
        authorized_operations={DomainOperation.READ_PUBLIC_RESEARCH},
        budget=DomainBudget(tool_call_limit=1, runtime_seconds=5),
    )


def app(action: CognitiveAction) -> CognitiveOrchestrator:
    registry = DomainRegistry()
    registry.register("example", Domain())
    return CognitiveOrchestrator(selector=Selector(action), dispatcher=DomainDispatcher(registry))


@pytest.mark.asyncio
async def test_guarded_domain_pipeline_returns_a_verified_public_response() -> None:
    result = await app(CognitiveAction(action_type=CognitiveActionType.INVOKE_DOMAIN, reason_code="DOMAIN_READ", reason="Read the requested result", domain_request=domain_request())).run(event())

    assert result.response.response_kind == "DOMAIN_RESULT"
    assert result.response.evidence_refs == ["source-1"]
    assert result.response.response_structure == "RESEARCH"
    assert result.response.sections[0].section_type == "FACTS"
    assert result.state.public_events == ["response.ready"]


@pytest.mark.asyncio
async def test_disabled_action_is_not_silently_downgraded_to_response() -> None:
    result = await app(CognitiveAction(action_type=CognitiveActionType.NOTIFY, reason_code="NOTIFY", reason="send a notification")).run(event())

    assert result.response.response_kind == "CAPABILITY_NOT_ENABLED"
    assert result.response.audit_codes == ["ACTION_NOT_ENABLED"]


@pytest.mark.asyncio
async def test_unregistered_domain_returns_limited_not_success() -> None:
    request = domain_request().model_copy(update={"domain": "missing"})
    result = await app(CognitiveAction(action_type=CognitiveActionType.INVOKE_DOMAIN, reason_code="DOMAIN_READ", reason="Read result", domain_request=request)).run(event())

    assert result.response.response_kind == "LIMITED"
    assert result.response.audit_codes == ["DOMAIN_NOT_REGISTERED"]
