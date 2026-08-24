"""§11.3 Data-quality：freshness / provenance 规则回归。"""

from __future__ import annotations

from bdlh_runtime.contracts.observation import DataQuality, Observation, ProvenanceRecord
from bdlh_runtime.guardrails import (
    DefaultDataQualityGuardrail,
    GuardrailContext,
    GuardrailDecision,
    evaluate_freshness,
    evaluate_provenance_depth,
)


def _ctx() -> GuardrailContext:
    return GuardrailContext(
        run_id="run-1",
        authenticated_user_id="user-1",
        enabled_actions=frozenset({"INVOKE_DOMAIN"}),
        enabled_domains=frozenset({"finance"}),
    )


def _ok_observation(**overrides: object) -> dict:
    payload = Observation(
        observation_id="obs-1",
        capability="market.get_realtime_quote",
        status="SUCCESS",
        data={"symbol": "600519", "price": 1.0},
        data_quality=DataQuality(completeness=1.0, freshness="CURRENT", quality_status="OK"),
        provenance=[
            ProvenanceRecord(
                source="provider-a",
                tool="market.get_realtime_quote",
                retrieved_at="2026-08-17T00:00:00+00:00",
            )
        ],
    ).model_dump(mode="json")
    payload.update(overrides)
    return payload


def test_freshness_blocks_stale_quality_status() -> None:
    payload = _ok_observation(data_quality={"completeness": 1.0, "freshness": "CURRENT", "quality_status": "STALE"})
    hit = evaluate_freshness(payload)
    assert hit is not None
    assert hit[0] == "DATA_STALE"
    result = DefaultDataQualityGuardrail().evaluate_data_quality(payload, context=_ctx())
    assert result.decision == GuardrailDecision.BLOCK
    assert result.audit_code == "DATA_STALE"
    assert result.rule_ids == ["DATA-FRESHNESS-001"]


def test_freshness_blocks_nested_expired_marker() -> None:
    payload = {
        "status": "COMPLETE",
        "nested": {"observations": [_ok_observation(data_quality={"freshness": "EXPIRED", "quality_status": "OK"})]},
    }
    # nested observation also needs valid provenance — keep from _ok_observation
    assert evaluate_freshness(payload)[0] == "DATA_STALE"


def test_provenance_blocks_missing_list_on_success_observation() -> None:
    payload = _ok_observation(provenance=[])
    hit = evaluate_provenance_depth(payload)
    assert hit is not None
    assert hit[0] == "PROVENANCE_REQUIRED"
    result = DefaultDataQualityGuardrail().evaluate_data_quality(payload, context=_ctx())
    assert result.audit_code == "PROVENANCE_REQUIRED"
    assert result.rule_ids == ["DATA-PROVENANCE-001"]


def test_provenance_blocks_incomplete_record() -> None:
    payload = _ok_observation(provenance=[{"source": "provider-a", "tool": "quote", "retrieved_at": ""}])
    hit = evaluate_provenance_depth(payload)
    assert hit is not None
    assert hit[0] == "PROVENANCE_INCOMPLETE"
    result = DefaultDataQualityGuardrail().evaluate_data_quality(payload, context=_ctx())
    assert result.audit_code == "PROVENANCE_INCOMPLETE"
    assert result.rule_ids == ["DATA-PROVENANCE-002"]


def test_domain_outcome_without_observations_still_allowed() -> None:
    """Cognitive 主路径传入 DomainOutcome dump；无 Observation 节点时不误杀。"""
    payload = {
        "request_id": "r1",
        "domain": "finance",
        "status": "COMPLETE",
        "established_facts": [{"fact_id": "f1", "statement": "ok", "source_refs": ["e1"]}],
        "confidence": {"level": "HIGH", "coverage_status": "COMPLETE"},
    }
    assert evaluate_freshness(payload) is None
    assert evaluate_provenance_depth(payload) is None
    result = DefaultDataQualityGuardrail().evaluate_data_quality(payload, context=_ctx())
    assert result.decision == GuardrailDecision.ALLOW


def test_ok_observation_passes_freshness_and_provenance() -> None:
    payload = _ok_observation()
    result = DefaultDataQualityGuardrail().evaluate_data_quality(payload, context=_ctx())
    assert result.decision == GuardrailDecision.ALLOW
