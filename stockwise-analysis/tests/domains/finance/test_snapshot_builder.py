"""M3 foundation：用户数据标准化与 fail-closed FinancialSnapshotBuilder。"""

from __future__ import annotations

from typing import Any

import pytest

from stockwise_analysis.contracts.observation import (
    DataQuality,
    Observation,
    ProvenanceRecord,
)
from stockwise_analysis.domains.contracts import DomainBudget, DomainOperation
from stockwise_analysis.domains.finance.authorization import (
    FinanceCapabilityAuthorizationPolicy,
)
from stockwise_analysis.domains.finance.contracts import (
    FinancialDataMode,
    FinancialDomainRequest,
    FinancialInstrument,
    FinancialIntent,
)
from stockwise_analysis.domains.finance.runtime import (
    ApplicationFinanceCapabilityExecutor,
)
from stockwise_analysis.domains.finance.snapshot_builder import (
    ACCOUNT_CAPABILITY,
    POSITIONS_CAPABILITY,
    RISK_PROFILE_CAPABILITY,
    FinancialSnapshotBuilder,
    FinancialSnapshotError,
    SnapshotIdentityError,
    UserFinancialObservationNormalizer,
)
from stockwise_analysis.tools.capabilities import build_default_capability_registry


def _request(user_id: str = "7") -> FinancialDomainRequest:
    return FinancialDomainRequest(
        request_id="m3-foundation",
        authenticated_user_id=user_id,
        objective="评估单一标的是否适合当前用户",
        financial_intent=FinancialIntent.SUITABILITY,
        analysis_type="comprehensive",
        instruments=[FinancialInstrument(symbol="600519", name="贵州茅台")],
        authorized_operations={
            DomainOperation.READ_MARKET_DATA,
            DomainOperation.READ_PUBLIC_RESEARCH,
            DomainOperation.RUN_ANALYSIS,
            DomainOperation.READ_PORTFOLIO,
            DomainOperation.READ_PROFILE,
        },
        budget=DomainBudget(
            tool_call_limit=20,
            runtime_seconds=120,
            model_call_limit=0,
        ),
    )


def _raw_observation(
    observation_id: str,
    capability: str,
    data: dict[str, Any] | None,
    *,
    status: str = "SUCCESS",
    source: str = "java-api",
    retrieved_at: str = "2026-08-10T10:00:00+08:00",
    data_mode: str | None = "LIVE",
) -> Observation:
    if data is not None and data_mode is not None and isinstance(data.get("metadata"), dict):
        metadata = data["metadata"]
        metadata.setdefault("schema_version", "financial-user-data.v2")
        metadata.setdefault("data_mode", data_mode)
        metadata.setdefault(
            "source_type",
            "USER_INPUT" if data_mode == "USER_CONFIRMED" else "BROKER_SYNC",
        )
        metadata.setdefault("data_time", retrieved_at)
        if data_mode == "USER_CONFIRMED":
            metadata.setdefault("confirmation_ref", f"confirm-{observation_id}")
    return Observation(
        observation_id=observation_id,
        capability=capability,
        status=status,
        data=data,
        data_quality=DataQuality(
            completeness=1.0 if status == "SUCCESS" else 0.0,
            quality_status="OK" if status == "SUCCESS" else "INVALID",
        ),
        provenance=[
            ProvenanceRecord(
                source=source,
                tool=capability,
                retrieved_at=retrieved_at,
            )
        ],
    )


def _normalize_all(
    observations: list[Observation],
    *,
    user_id: str = "7",
) -> list[Observation]:
    normalizer = UserFinancialObservationNormalizer()
    return [
        normalizer.normalize(item, authenticated_user_id=user_id)
        for item in observations
    ]


def _complete_raw_observations() -> list[Observation]:
    return [
        _raw_observation(
            "obs-positions",
            POSITIONS_CAPABILITY,
            {
                "metadata": {"user_id": 7},
                "positions": [
                    {
                        "symbol": "600519",
                        "name": "贵州茅台",
                        "quantity": 100,
                        "market_value": 150_000,
                        "weight_pct": 15.0,
                        "sector": "白酒",
                    }
                ],
            },
            retrieved_at="2026-08-10T10:00:01+08:00",
        ),
        _raw_observation(
            "obs-account",
            ACCOUNT_CAPABILITY,
            {
                "metadata": {"user_id": 7},
                "total_assets": 1_000_000,
                "cash": 200_000,
                "currency": "CNY",
                "liquid_assets": 200_000,
                "near_term_cash_needs": 50_000,
            },
            retrieved_at="2026-08-10T10:00:02+08:00",
        ),
        _raw_observation(
            "obs-risk",
            RISK_PROFILE_CAPABILITY,
            {
                "metadata": {"user_id": 7},
                "risk_tolerance": "moderate",
                "max_loss_tolerance_pct": 20.0,
            },
            retrieved_at="2026-08-10T10:00:03+08:00",
        ),
    ]


def test_normalizer_rejects_cross_user_data() -> None:
    observation = _complete_raw_observations()[0]

    with pytest.raises(SnapshotIdentityError) as error:
        UserFinancialObservationNormalizer().normalize(
            observation,
            authenticated_user_id="8",
        )

    assert error.value.code == "SNAPSHOT_IDENTITY_MISMATCH"


def test_normalizer_does_not_promote_legacy_java_success_or_target_values() -> None:
    raw = _raw_observation(
        "obs-positions",
        POSITIONS_CAPABILITY,
        {
            "metadata": {"user_id": 7},
            "positions": [
                {
                    "symbol": "600519",
                    "quantity": 100,
                    "cost_price": 1500,
                    "target_weight": 20,
                }
            ],
        },
        data_mode=None,
    )

    normalized = _normalize_all([raw])[0]
    position = normalized.data["positions"][0]

    assert position["market_value"] is None
    assert position["weight_pct"] is None
    assert normalized.data["user_id"] == "7"
    assert normalized.data["data_mode"] == "UNAVAILABLE"


def test_normalizer_accepts_server_confirmed_v2_metadata_and_preserves_identity() -> None:
    raw = _raw_observation(
        "obs-profile",
        RISK_PROFILE_CAPABILITY,
        {
            "metadata": {"user_id": 7},
            "risk_tolerance": "balanced",
            "max_loss_tolerance_pct": 25,
        },
        data_mode="USER_CONFIRMED",
    )

    normalized = _normalize_all([raw])[0]

    assert normalized.data["data_mode"] == "USER_CONFIRMED"
    assert normalized.data["source_type"] == "USER_INPUT"
    assert normalized.data["confirmation_ref"] == "confirm-obs-profile"
    assert normalized.data["risk_profile"]["max_loss_tolerance_pct"] == 25


def test_complete_normalized_inputs_build_a_deterministic_live_snapshot() -> None:
    observations = _normalize_all(_complete_raw_observations())
    builder = FinancialSnapshotBuilder()

    first = builder.build(
        request=_request(),
        observations=observations,
        execution_environment="test",
    )
    second = builder.build(
        request=_request(),
        observations=list(reversed(observations)),
        execution_environment="test",
    )

    assert first.model_dump() == second.model_dump()
    assert first.data_mode == FinancialDataMode.LIVE
    assert first.completeness == "COMPLETE"
    assert first.captured_at.isoformat() == "2026-08-10T10:00:03+08:00"
    assert first.positions[0].market_value == 150_000
    assert first.positions[0].weight_pct == 15.0
    assert first.account is not None and first.account.total_assets == 1_000_000
    assert first.risk_profile is not None
    assert first.risk_profile.risk_level == "BALANCED"
    assert first.risk_profile.max_loss_tolerance_pct == 20.0
    assert first.liquidity is not None and first.liquidity.status == "OK"
    assert first.limitations == []


def test_current_repository_fields_build_partial_without_fabricating_values() -> None:
    raw = [
        _raw_observation(
            "obs-positions",
            POSITIONS_CAPABILITY,
            {
                "metadata": {"user_id": 7},
                "positions": [
                    {
                        "symbol": "600519",
                        "quantity": 100,
                        "cost_price": 1500,
                        "target_weight": 20,
                    }
                ],
            },
        ),
        _raw_observation(
            "obs-account",
            ACCOUNT_CAPABILITY,
            {
                "metadata": {"user_id": 7},
                "cash": 100_000,
                "monthly_budget": 10_000,
                "cash_reserve_ratio": 0.2,
            },
        ),
        _raw_observation(
            "obs-risk",
            RISK_PROFILE_CAPABILITY,
            {
                "metadata": {"user_id": 7},
                "risk_tolerance": "moderate",
                "cash_reserve_ratio": 0.2,
            },
        ),
    ]

    snapshot = FinancialSnapshotBuilder().build(
        request=_request(),
        observations=_normalize_all(raw),
        execution_environment="development",
    )

    assert snapshot.data_mode == FinancialDataMode.LIVE
    assert snapshot.completeness == "PARTIAL"
    assert snapshot.positions[0].market_value is None
    assert snapshot.positions[0].weight_pct is None
    assert snapshot.account is not None and snapshot.account.total_assets is None
    assert snapshot.risk_profile is not None
    assert snapshot.risk_profile.max_loss_tolerance_pct is None
    assert snapshot.liquidity is not None
    assert snapshot.liquidity.near_term_cash_needs is None
    assert any("concentration unavailable" in item for item in snapshot.limitations)


def test_mock_user_data_is_never_promoted_to_live_or_complete() -> None:
    raw = _complete_raw_observations()
    for observation in raw:
        observation.data["is_mock"] = True
        observation.provenance[0].source = "mock-java"

    snapshot = FinancialSnapshotBuilder().build(
        request=_request(),
        observations=_normalize_all(raw),
        execution_environment="development",
    )

    assert snapshot.data_mode == FinancialDataMode.MOCK
    assert snapshot.is_mock is True
    assert snapshot.completeness == "LIMITED"
    assert any("MOCK" in item for item in snapshot.limitations)


def test_partial_user_observation_propagates_to_snapshot_completeness() -> None:
    raw = _complete_raw_observations()
    raw[-1].status = "PARTIAL"
    raw[-1].data_quality = DataQuality(
        completeness=0.8,
        quality_status="PARTIAL",
    )

    snapshot = FinancialSnapshotBuilder().build(
        request=_request(),
        observations=_normalize_all(raw),
        execution_environment="development",
    )

    assert snapshot.data_mode == FinancialDataMode.LIVE
    assert snapshot.completeness == "PARTIAL"
    assert "Partial user capability: user.get_risk_profile" in snapshot.limitations


def test_unavailable_observations_build_an_explicit_unavailable_snapshot() -> None:
    observations = [
        _raw_observation(
            f"obs-{index}",
            capability,
            None,
            status="UNAVAILABLE",
            retrieved_at=f"2026-08-10T10:00:0{index}+08:00",
        )
        for index, capability in enumerate(
            sorted({POSITIONS_CAPABILITY, ACCOUNT_CAPABILITY, RISK_PROFILE_CAPABILITY}),
            start=1,
        )
    ]

    snapshot = FinancialSnapshotBuilder().build(
        request=_request(),
        observations=_normalize_all(observations),
        execution_environment="production",
    )

    assert snapshot.data_mode == FinancialDataMode.UNAVAILABLE
    assert snapshot.completeness == "LIMITED"
    assert len(snapshot.limitations) == 3


def test_snapshot_builder_rejects_unverifiable_time() -> None:
    observation = _complete_raw_observations()[0]
    observation.provenance = []
    normalized = _normalize_all([observation])

    with pytest.raises(FinancialSnapshotError, match="retrieved_at"):
        FinancialSnapshotBuilder().build(
            request=_request(),
            observations=normalized,
            execution_environment="test",
        )


def test_m3_authorization_is_exact_and_excludes_transaction_history() -> None:
    registry = build_default_capability_registry()
    policy = FinanceCapabilityAuthorizationPolicy(registry)

    allowed = policy.allowed_capabilities({
        DomainOperation.READ_PORTFOLIO,
        DomainOperation.READ_PROFILE,
    })

    assert allowed == {
        POSITIONS_CAPABILITY,
        ACCOUNT_CAPABILITY,
        RISK_PROFILE_CAPABILITY,
    }
    assert "portfolio.get_transaction_history" not in allowed
    assert "portfolio.delete_positions" not in allowed


@pytest.mark.asyncio
async def test_application_executor_routes_only_exact_user_capabilities_to_java() -> None:
    class JavaAdapter:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        async def execute(self, capability: str, arguments: dict[str, Any]) -> Observation:
            self.calls.append((capability, arguments))
            return _raw_observation(
                "obs-java",
                capability,
                {"metadata": {"user_id": 7}, "positions": []},
            )

    java = JavaAdapter()
    executor = ApplicationFinanceCapabilityExecutor(
        gateway_adapter=object(),
        web_search_adapter=object(),
        analysis_capability=object(),
        java_adapter=java,
    )

    result = await executor.execute(
        POSITIONS_CAPABILITY,
        {"user_id": "7"},
        request_id="m3-route",
    )

    assert isinstance(result, Observation)
    assert java.calls == [(POSITIONS_CAPABILITY, {"user_id": "7"})]
    with pytest.raises(ValueError, match="does not support"):
        await executor.execute(
            "portfolio.delete_positions",
            {"user_id": "7"},
            request_id="m3-route",
        )
