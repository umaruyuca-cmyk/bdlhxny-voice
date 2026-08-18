"""Deep Research 契约、调用策略与隔离执行器测试（ADR-016 / §6.5）。"""

from __future__ import annotations

import pytest

from bdlh_runtime.tools.deep_research import (
    DEEP_SEARCH_CAPABILITY,
    DeepResearchRequest,
    DeepResearchToolExecutor,
    FakeAtomicSearchPort,
    assemble_research_bundle,
    evaluate_deep_research_trigger,
)
from bdlh_runtime.tools.deep_research.contracts import ResearchFinding, ResearchSource


def _request(**kwargs) -> DeepResearchRequest:
    base = {
        "request_id": "req-1",
        "question": "比较两家公司的公开舆情与风险",
        "objective": "支持研究决策",
    }
    base.update(kwargs)
    return DeepResearchRequest.model_validate(base)


def test_trigger_default_is_shallow_when_no_signals():
    decision = evaluate_deep_research_trigger(
        _request(question="茅台现在股价多少", objective="查报价"),
        feature_enabled=True,
        in_allowed=True,
        entitled=True,
    )
    assert decision.should_deep is False


def test_trigger_any_rule_enables_deep_when_gates_pass():
    decision = evaluate_deep_research_trigger(
        _request(
            question="请做深度调研并交叉验证",
            research_topics=["舆情", "风险"],
            success_criteria=["覆盖舆情来源", "列出主要风险点"],
        ),
        feature_enabled=True,
        in_allowed=True,
        entitled=True,
        expected_independent_queries=3,
    )
    assert decision.should_deep is True
    assert "explicit_user_request" in decision.deep_trigger_reasons
    assert "research_topics_ge_2" in decision.deep_trigger_reasons
    assert "success_criteria_ge_2" in decision.deep_trigger_reasons
    assert "expected_queries_ge_3" in decision.deep_trigger_reasons


def test_trigger_blocked_by_feature_flag_even_if_signals_match():
    decision = evaluate_deep_research_trigger(
        _request(question="需要深度调研报告"),
        feature_enabled=False,
        in_allowed=True,
        entitled=True,
    )
    assert decision.should_deep is False
    assert "feature_flag_off" in decision.blocked_reasons
    assert decision.deep_trigger_reasons == ()


def test_empty_success_criteria_do_not_count():
    decision = evaluate_deep_research_trigger(
        _request(success_criteria=["", "·", "ab"]),
        feature_enabled=True,
        in_allowed=True,
        entitled=True,
    )
    assert "success_criteria_ge_2" not in decision.reasons


def test_assemble_rejects_complete_without_sources():
    bundle = assemble_research_bundle(
        _request(research_topics=["舆情"], success_criteria=["有来源"]),
        findings=[ResearchFinding(finding_id="f1", statement="x", source_ids=["missing"])],
        sources=[],
    )
    assert bundle.status == "FAILED"
    assert "no_valid_sources" in bundle.limitations


def test_assemble_complete_with_closed_sources():
    bundle = assemble_research_bundle(
        _request(research_topics=["舆情"], success_criteria=["有来源"]),
        findings=[ResearchFinding(finding_id="f1", statement="有公开讨论", source_ids=["s1"])],
        sources=[
            ResearchSource(
                source_id="s1",
                title="t",
                url="https://example.com/a",
                retrieved_at="2026-08-15T00:00:00Z",
            )
        ],
    )
    assert bundle.status == "COMPLETE"


@pytest.mark.asyncio
async def test_executor_disabled_by_default():
    executor = DeepResearchToolExecutor(enabled=False)
    obs = await executor.execute(
        DEEP_SEARCH_CAPABILITY,
        _request().model_dump(),
    )
    assert obs.status == "UNAVAILABLE"
    assert obs.error_code == "DEEP_RESEARCH_NOT_ENABLED"


@pytest.mark.asyncio
async def test_executor_isolation_path_with_fake_search():
    executor = DeepResearchToolExecutor(enabled=True, atomic_search=FakeAtomicSearchPort())
    obs = await executor.execute(
        DEEP_SEARCH_CAPABILITY,
        _request(research_topics=["舆情"], success_criteria=["有来源"]).model_dump(),
    )
    assert obs.capability == DEEP_SEARCH_CAPABILITY
    assert obs.status in {"SUCCESS", "PARTIAL"}
    assert obs.data["status"] == "PARTIAL"
    assert "isolation_stub_no_supervisor" in obs.data["limitations"]
    assert obs.data["sources"]


@pytest.mark.asyncio
async def test_executor_does_not_handle_web_search():
    executor = DeepResearchToolExecutor(enabled=True, atomic_search=FakeAtomicSearchPort())
    obs = await executor.execute("research.web_search", {"query": "x"})
    assert obs.status == "FAILED"
    assert obs.error_code == "DEEP_RESEARCH_INVALID_REQUEST"


@pytest.mark.asyncio
async def test_fake_atomic_search_unavailable_is_honest():
    port = FakeAtomicSearchPort(unavailable=True)
    batch = await port.search(
        __import__(
            "bdlh_runtime.tools.deep_research.atomic_search",
            fromlist=["AtomicSearchRequest"],
        ).AtomicSearchRequest(request_id="r1", queries=["q"])
    )
    assert batch.status == "UNAVAILABLE"
    assert batch.error_code == "ATOMIC_SEARCH_UNAVAILABLE"
