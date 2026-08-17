from bdlh_runtime.cognitive import (
    CognitiveAction,
    CognitiveActionType,
    DefaultActionPolicy,
)


def _action(action_type: CognitiveActionType) -> CognitiveAction:
    return CognitiveAction(
        action_type=action_type,
        reason_code="TEST",
        reason="test action",
    )


def test_default_policy_enables_exactly_the_three_m4_actions() -> None:
    policy = DefaultActionPolicy()

    assert policy.enabled_actions == {
        CognitiveActionType.RESPOND,
        CognitiveActionType.ASK_USER,
        CognitiveActionType.INVOKE_DOMAIN,
    }


def test_disabled_action_returns_stable_rejection_instead_of_response() -> None:
    result = DefaultActionPolicy().evaluate(_action(CognitiveActionType.CREATE_TASK))

    assert result.decision == "REJECTED"
    assert result.audit_code == "ACTION_NOT_ENABLED"
    assert "CREATE_TASK" in (result.public_reason or "")
