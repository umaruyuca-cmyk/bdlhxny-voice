from __future__ import annotations

import pytest

from bdlh_runtime.config import Settings
from bdlh_runtime.runtime.errors import ConfigurationError
from bdlh_runtime.runtime.rollout import (
    CognitiveExecutionProgress,
    CognitiveTrafficRouter,
    RolloutConfig,
    RolloutMode,
    RuntimePath,
    RolloutHealthPolicy,
    approved_test_gate,
    build_rollout_router,
)


def test_rollout_defaults_to_legacy_and_requires_authenticated_user() -> None:
    off = CognitiveTrafficRouter(RolloutConfig())
    all_users = CognitiveTrafficRouter(
        RolloutConfig(mode=RolloutMode.ALL, gate=approved_test_gate())
    )

    assert off.decide(user_id="7", session_id="s").path == RuntimePath.LEGACY
    anonymous = all_users.decide(user_id=None, session_id="s")
    assert anonymous.path == RuntimePath.LEGACY
    assert anonymous.reason_code == "AUTHENTICATED_USER_REQUIRED"


def test_internal_rollout_selects_only_configured_users() -> None:
    router = CognitiveTrafficRouter(RolloutConfig(
        mode=RolloutMode.INTERNAL,
        internal_user_ids=frozenset({"7"}),
        gate=approved_test_gate(),
    ))

    assert router.decide(user_id="7", session_id="s").path == RuntimePath.COGNITIVE
    assert router.decide(user_id="8", session_id="s").path == RuntimePath.LEGACY


def test_percentage_rollout_is_stable_for_user_and_session() -> None:
    router = CognitiveTrafficRouter(RolloutConfig(
        mode=RolloutMode.PERCENTAGE,
        percentage=37,
        gate=approved_test_gate(),
    ))

    decisions = [router.decide(user_id="7", session_id="stable-session") for _ in range(20)]

    assert len({item.path for item in decisions}) == 1
    assert len({item.bucket for item in decisions}) == 1
    assert decisions[0].bucket is not None


def test_unapproved_rollout_fails_closed_to_legacy() -> None:
    router = CognitiveTrafficRouter(RolloutConfig(
        mode=RolloutMode.ALL,
    ))

    decision = router.decide(user_id="7", session_id="s")

    assert decision.path == RuntimePath.LEGACY
    assert decision.reason_code == "ROLLOUT_GATE_BLOCKED"


def test_production_rollout_cannot_start_without_storage_and_approval() -> None:
    settings = Settings(
        environment="production",
        cognitive_rollout_mode="internal",
        cognitive_rollout_internal_user_ids=frozenset({"7"}),
    )

    with pytest.raises(ConfigurationError, match="持久化"):
        build_rollout_router(settings, production_storage_ready=False)
    with pytest.raises(ConfigurationError, match="门禁未通过"):
        build_rollout_router(settings, production_storage_ready=True)


def test_fallback_is_disabled_as_soon_as_any_observable_side_effect_starts() -> None:
    progress = CognitiveExecutionProgress()
    assert progress.automatic_fallback_allowed

    progress.domain_request_started = True
    assert not progress.automatic_fallback_allowed


def test_health_policy_requests_rollback_after_error_threshold_is_exceeded() -> None:
    policy = RolloutHealthPolicy(
        minimum_cognitive_runs=10,
        maximum_error_rate=0.10,
        maximum_fallback_rate=0.20,
    )

    decision = policy.evaluate({
        "completed:cognitive_finance": 8,
        "cognitive_error:cognitive_finance": 2,
        "automatic_fallback:cognitive_finance": 3,
    })

    assert decision.rollback_required
    assert decision.reason_codes == (
        "COGNITIVE_ERROR_RATE_EXCEEDED",
        "AUTOMATIC_FALLBACK_RATE_EXCEEDED",
    )
