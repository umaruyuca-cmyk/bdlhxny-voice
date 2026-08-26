"""Deep Research 相关四时点 Guardrail 规则。"""

from __future__ import annotations

from bdlh_runtime.engine import (
    CognitiveAction,
    CognitiveActionType,
    DomainBudget,
    DomainOperation,
    DomainRequest,
    PublicResponse,
)
from bdlh_runtime.guardrails import (
    DefaultActionGuardrail,
    DefaultDataQualityGuardrail,
    DefaultPlanGuardrail,
    DefaultResponseGuardrail,
    GuardrailContext,
    GuardrailDecision,
)
from bdlh_runtime.tools.deep_research import DEEP_SEARCH_CAPABILITY


def _ctx(*, caps: frozenset[str] | None = None) -> GuardrailContext:
    return GuardrailContext(
        run_id="run-1",
        authenticated_user_id="user-1",
        enabled_actions=frozenset({"INVOKE_DOMAIN"}),
        enabled_domains=frozenset({"finance"}),
        authorized_operations=frozenset({"READ_PUBLIC_RESEARCH"}),
        authorized_capabilities=caps if caps is not None else frozenset(),
    )


def _domain_action(*, objective: str, criteria: list[str] | None = None) -> CognitiveAction:
    return CognitiveAction(
        action_type=CognitiveActionType.INVOKE_DOMAIN,
        reason_code="READ",
        reason="研究",
        domain_request=DomainRequest(
            request_id="r1",
            domain="finance",
            authenticated_user_id="user-1",
            objective=objective,
            success_criteria=list(criteria or []),
            authorized_operations={DomainOperation.READ_PUBLIC_RESEARCH},
            budget=DomainBudget(tool_call_limit=3, runtime_seconds=30),
        ),
    )


def test_plan_blocks_deep_when_capability_missing_from_whitelist() -> None:
    action = _domain_action(
        objective="请做深度调研并交叉验证",
        criteria=["有来源A", "有来源B"],
    )
    result = DefaultPlanGuardrail().evaluate_plan(
        action,
        context=_ctx(caps=frozenset({"research.web_search"})),
    )
    assert result.decision == GuardrailDecision.BLOCK
    assert result.audit_code == "DEEP_RESEARCH_NOT_AUTHORIZED"


def test_plan_allows_deep_when_capability_authorized() -> None:
    action = _domain_action(objective="请做深度调研并交叉验证")
    result = DefaultPlanGuardrail().evaluate_plan(
        action,
        context=_ctx(caps=frozenset({DEEP_SEARCH_CAPABILITY, "research.web_search"})),
    )
    assert result.decision == GuardrailDecision.ALLOW


def test_plan_skips_deep_gate_when_capabilities_unset() -> None:
    """兼容尚未填充 authorized_capabilities 的装配。"""
    action = _domain_action(objective="请做深度调研并交叉验证")
    result = DefaultPlanGuardrail().evaluate_plan(action, context=_ctx(caps=frozenset()))
    assert result.decision == GuardrailDecision.ALLOW


def test_action_blocks_unauthorized_deep() -> None:
    action = _domain_action(objective="深入研究公开舆情", criteria=["条件一足够长", "条件二足够长"])
    result = DefaultActionGuardrail().evaluate_action(
        action,
        context=_ctx(caps=frozenset({"market.get_news"})),
    )
    assert result.audit_code == "DEEP_RESEARCH_NOT_AUTHORIZED"


def test_data_quality_blocks_complete_without_sources() -> None:
    payload = {
        "capability": DEEP_SEARCH_CAPABILITY,
        "status": "SUCCESS",
        "data": {
            "schema_version": "research-bundle.v1",
            "request_id": "r1",
            "question": "q",
            "status": "COMPLETE",
            "findings": [],
            "sources": [],
            "limitations": [],
        },
    }
    result = DefaultDataQualityGuardrail().evaluate_data_quality(payload, context=_ctx())
    assert result.audit_code == "RESEARCH_COMPLETE_WITHOUT_SOURCES"


def test_data_quality_blocks_unclosed_finding() -> None:
    payload = {
        "capability": DEEP_SEARCH_CAPABILITY,
        "status": "SUCCESS",
        "data": {
            "schema_version": "research-bundle.v1",
            "request_id": "r1",
            "question": "q",
            "status": "PARTIAL",
            "findings": [{"finding_id": "f1", "statement": "x", "source_ids": ["missing"]}],
            "sources": [
                {
                    "source_id": "s1",
                    "title": "t",
                    "url": "https://example.com/a",
                    "retrieved_at": "2026-08-15T00:00:00Z",
                }
            ],
        },
    }
    result = DefaultDataQualityGuardrail().evaluate_data_quality(payload, context=_ctx())
    assert result.audit_code == "RESEARCH_FINDING_SOURCE_UNCLOSED"


def test_data_quality_blocks_non_http_url() -> None:
    payload = {
        "capability": DEEP_SEARCH_CAPABILITY,
        "status": "SUCCESS",
        "data": {
            "schema_version": "research-bundle.v1",
            "request_id": "r1",
            "question": "q",
            "status": "PARTIAL",
            "findings": [{"finding_id": "f1", "statement": "x", "source_ids": ["s1"]}],
            "sources": [
                {
                    "source_id": "s1",
                    "title": "t",
                    "url": "javascript:alert(1)",
                    "retrieved_at": "2026-08-15T00:00:00Z",
                }
            ],
        },
    }
    result = DefaultDataQualityGuardrail().evaluate_data_quality(payload, context=_ctx())
    assert result.audit_code == "RESEARCH_URL_SCHEME_BLOCKED"


def test_data_quality_allows_partial_with_closed_sources() -> None:
    payload = {
        "capability": DEEP_SEARCH_CAPABILITY,
        "status": "SUCCESS",
        "data": {
            "schema_version": "research-bundle.v1",
            "request_id": "r1",
            "question": "q",
            "status": "PARTIAL",
            "findings": [{"finding_id": "f1", "statement": "有讨论", "source_ids": ["s1"]}],
            "sources": [
                {
                    "source_id": "s1",
                    "title": "t",
                    "url": "https://example.com/a",
                    "retrieved_at": "2026-08-15T00:00:00Z",
                    "summary": "ok",
                }
            ],
            "limitations": ["rule_based_orchestration"],
        },
    }
    result = DefaultDataQualityGuardrail().evaluate_data_quality(payload, context=_ctx())
    assert result.decision == GuardrailDecision.ALLOW


def test_response_blocks_research_suitability_mix() -> None:
    result = DefaultResponseGuardrail().evaluate_response(
        PublicResponse(
            response_kind="ANSWER",
            message="根据公开研究，该股适合你买入",
            evidence_refs=["e1"],
        ),
        context=_ctx(),
    )
    assert result.audit_code == "RESEARCH_SUITABILITY_MIXED"


def test_response_blocks_provider_secret_leak() -> None:
    result = DefaultResponseGuardrail().evaluate_response(
        PublicResponse(
            response_kind="ANSWER",
            message="调用了 dashscope.aliyuncs.com 与 sk-secret",
        ),
        context=_ctx(),
    )
    assert result.audit_code == "RESEARCH_SECRET_LEAK"
