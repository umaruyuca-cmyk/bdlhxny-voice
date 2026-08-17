from __future__ import annotations

from typing import Any

import pytest

from bdlh_runtime.contracts.observation import DataQuality, Observation, ProvenanceRecord
from bdlh_runtime.domains.contracts import DomainBudget, DomainOperation
from bdlh_runtime.domains.finance.authorization import FinanceCapabilityAuthorizationPolicy
from bdlh_runtime.domains.finance.contracts import (
    InstrumentMention,
    InstrumentResolutionRequest,
)
from bdlh_runtime.domains.finance.instrument_resolver import FinanceInstrumentResolver
from bdlh_runtime.tools.capabilities import build_default_capability_registry


class ResolverExecutor:
    def __init__(self, data: Any, *, status: str = "SUCCESS") -> None:
        self.data = data
        self.status = status
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, capability: str, arguments: dict[str, Any], *, request_id: str) -> Observation:
        self.calls.append((capability, arguments))
        return Observation(
            observation_id="resolver-1",
            capability=capability,
            status=self.status,  # type: ignore[arg-type]
            data=self.data,
            data_quality=DataQuality(completeness=1.0, quality_status="OK"),
            provenance=[ProvenanceRecord(source="market-master", tool=capability, retrieved_at="2026-08-11T10:00:00+08:00")],
        )


def request(*, mention_type: str = "NAME", operations: set[DomainOperation] | None = None) -> InstrumentResolutionRequest:
    return InstrumentResolutionRequest(
        request_id="resolution-1",
        authenticated_user_id="user-1",
        objective="Resolve the instrument mentioned by the user",
        authorized_operations=operations or {DomainOperation.READ_MARKET_DATA},
        budget=DomainBudget(tool_call_limit=1, runtime_seconds=5),
        mention=InstrumentMention(raw_text="贵州茅台", normalized_text="贵州茅台", mention_type=mention_type),  # type: ignore[arg-type]
    )


def resolver(data: Any, *, status: str = "SUCCESS") -> tuple[FinanceInstrumentResolver, ResolverExecutor]:
    registry = build_default_capability_registry()
    executor = ResolverExecutor(data, status=status)
    return (
        FinanceInstrumentResolver(
            registry=registry,
            authorization=FinanceCapabilityAuthorizationPolicy(registry),
            executor=executor,
        ),
        executor,
    )


@pytest.mark.asyncio
async def test_resolves_a_single_source_validated_exact_name() -> None:
    service, executor = resolver({"symbol": "600519", "name": "贵州茅台", "exchange": "SSE", "match_type": "EXACT_NAME"})

    outcome = await service.resolve(request())

    assert outcome.resolution_status == "RESOLVED"
    assert outcome.selected is not None
    assert outcome.selected.canonical_symbol == "600519"
    assert outcome.selected.source_refs == ["market-master:market.resolve_instrument"]
    assert executor.calls == [("market.resolve_instrument", {"symbol": "贵州茅台"})]


@pytest.mark.asyncio
async def test_returns_ambiguous_for_multiple_or_fuzzy_candidates() -> None:
    service, _ = resolver({"candidates": [
        {"symbol": "000001", "name": "平安银行", "exchange": "SZSE", "match_type": "EXACT_NAME"},
        {"symbol": "601318", "name": "中国平安", "exchange": "SSE", "match_type": "EXACT_NAME"},
    ]})

    outcome = await service.resolve(request())

    assert outcome.resolution_status == "AMBIGUOUS"
    assert outcome.selected is None
    assert len(outcome.candidates) == 2


@pytest.mark.asyncio
async def test_normalized_cn_financial_search_keeps_ambiguity() -> None:
    import json

    from bdlh_runtime.observations.normalizer import ObservationNormalizer

    raw = json.dumps(
        [
            {"code": "000001", "name": "平安银行"},
            {"code": "601318", "name": "中国平安"},
        ]
    )
    normalized = ObservationNormalizer().normalize(
        Observation(
            observation_id="resolver-norm",
            capability="market.resolve_instrument",
            status="SUCCESS",
            data={"raw_text": raw},
            data_quality=DataQuality(completeness=1.0, quality_status="OK"),
            provenance=[
                ProvenanceRecord(
                    source="cn-financial-mcp",
                    tool="search_stock",
                    retrieved_at="2026-08-11T10:00:00+08:00",
                )
            ],
        )
    )
    registry = build_default_capability_registry()

    class NormalizedExecutor:
        async def execute(self, capability: str, arguments: dict[str, Any], *, request_id: str) -> Observation:
            del capability, arguments, request_id
            return normalized

    service = FinanceInstrumentResolver(
        registry=registry,
        authorization=FinanceCapabilityAuthorizationPolicy(registry),
        executor=NormalizedExecutor(),
    )

    outcome = await service.resolve(request(mention_type="NAME"))

    assert outcome.resolution_status == "AMBIGUOUS"
    assert len(outcome.candidates) == 2
    assert {item.exchange for item in outcome.candidates} == {"SSE", "SZSE"}


@pytest.mark.asyncio
async def test_rejects_candidate_when_exchange_cannot_be_established() -> None:
    service, _ = resolver({"symbol": "ABC", "name": "Unknown Issuer"})

    outcome = await service.resolve(request())

    assert outcome.resolution_status == "NOT_FOUND"


@pytest.mark.asyncio
async def test_infers_cn_exchange_when_source_omits_it() -> None:
    service, _ = resolver({"symbol": "600519", "name": "贵州茅台"})

    outcome = await service.resolve(request())

    assert outcome.resolution_status == "RESOLVED"
    assert outcome.selected is not None
    assert outcome.selected.exchange == "SSE"


@pytest.mark.asyncio
async def test_rejects_mock_provenance_before_identity_is_established() -> None:
    registry = build_default_capability_registry()

    class MockExecutor:
        async def execute(self, capability: str, arguments: dict[str, Any], *, request_id: str) -> Observation:
            del arguments, request_id
            return Observation(
                observation_id="resolver-mock",
                capability=capability,
                status="SUCCESS",
                data={"symbol": "600519", "name": "贵州茅台", "exchange": "SSE"},
                data_quality=DataQuality(completeness=1.0, quality_status="OK"),
                provenance=[
                    ProvenanceRecord(
                        source="mock-market",
                        tool=capability,
                        retrieved_at="2026-08-11T10:00:00+08:00",
                    )
                ],
            )

    service = FinanceInstrumentResolver(
        registry=registry,
        authorization=FinanceCapabilityAuthorizationPolicy(registry),
        executor=MockExecutor(),
    )

    outcome = await service.resolve(request())

    assert outcome.resolution_status == "UNAVAILABLE"
    assert outcome.errors[0].code == "NON_PRODUCTION_DATA"


@pytest.mark.asyncio
async def test_requires_market_read_authorization() -> None:
    service, executor = resolver({"symbol": "600519", "name": "贵州茅台", "exchange": "SSE"})

    outcome = await service.resolve(request(operations={DomainOperation.READ_PUBLIC_RESEARCH}))

    assert outcome.resolution_status == "UNAVAILABLE"
    assert outcome.errors[0].code == "REQUIRED_CAPABILITY_NOT_AUTHORIZED"
    assert executor.calls == []
