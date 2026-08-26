"""通用 DomainRequest / CognitiveAction 契约回归。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bdlh_runtime.engine.contracts import (
    ACTION_NOT_ENABLED,
    ENABLED_ACTION_TYPES,
    CognitiveAction,
    CognitiveActionType,
    DomainBudget,
    DomainOperation,
    DomainRequest,
    is_action_enabled,
)


def _budget() -> DomainBudget:
    return DomainBudget(tool_call_limit=4, runtime_seconds=30, model_call_limit=1)


def _domain_request(**overrides) -> DomainRequest:
    values = {
        "request_id": "domain-1",
        "domain": "example",
        "authenticated_user_id": "user-1",
        "objective": "研究指定标的",
        "success_criteria": ["返回可追溯证据"],
        "authorized_operations": {
            DomainOperation.READ_MARKET_DATA,
            DomainOperation.RUN_ANALYSIS,
        },
        "budget": _budget(),
    }
    values.update(overrides)
    return DomainRequest(**values)


def test_domain_request_round_trip_is_lossless_and_strict() -> None:
    request = _domain_request()
    restored = DomainRequest.model_validate_json(request.model_dump_json())
    assert restored == request
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _domain_request(unbounded_payload={"hidden": "value"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authenticated_user_id", ""),
        ("objective", ""),
        ("authorized_operations", set()),
    ],
)
def test_domain_request_rejects_invalid_boundary_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _domain_request(**{field: value})


def test_domain_budget_rejects_negative_or_zero_runtime() -> None:
    with pytest.raises(ValidationError):
        DomainBudget(tool_call_limit=-1, runtime_seconds=30)
    with pytest.raises(ValidationError):
        DomainBudget(tool_call_limit=1, runtime_seconds=0)


def test_cognitive_action_is_the_single_nine_action_contract() -> None:
    assert len(CognitiveActionType) == 9
    assert {
        CognitiveActionType.RESPOND,
        CognitiveActionType.ASK_USER,
        CognitiveActionType.INVOKE_DOMAIN,
    } == ENABLED_ACTION_TYPES
    assert ACTION_NOT_ENABLED == "ACTION_NOT_ENABLED"
    assert not is_action_enabled(CognitiveActionType.CREATE_TASK)


def test_cognitive_action_enforces_domain_payload_boundary() -> None:
    with pytest.raises(ValidationError, match="requires a domain_request"):
        CognitiveAction(
            action_type=CognitiveActionType.INVOKE_DOMAIN,
            reason_code="DOMAIN_REQUIRED",
            reason="需要领域数据",
        )
    with pytest.raises(ValidationError, match="only INVOKE_DOMAIN"):
        CognitiveAction(
            action_type=CognitiveActionType.RESPOND,
            reason_code="DIRECT_RESPONSE",
            reason="稳定知识问题",
            domain_request=_domain_request(),
        )
