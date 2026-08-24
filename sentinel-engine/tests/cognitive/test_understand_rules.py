"""规则 Understand 与 Goal 立案测试。"""

from __future__ import annotations

from tests.helpers_understand import rule_based_understand


def test_knowledge_question_does_not_need_external() -> None:
    out = rule_based_understand("什么是市盈率")
    assert out.needs_external is False
    assert out.goals[0].objective.startswith("解释概念")


def test_research_message_needs_instrument_when_missing() -> None:
    out = rule_based_understand("帮我看看走势怎么样")
    assert out.needs_external is True
    assert "instrument" in out.missing


def test_code_message_extracts_instrument_and_topics() -> None:
    out = rule_based_understand("看下 600519 的新闻和资金流")
    assert out.entities.instruments == ["600519"]
    assert "news" in out.goals[0].requested_topics
    assert "money_flow" in out.goals[0].requested_topics
    assert out.missing == []


def test_suitability_marks_profile_and_account() -> None:
    out = rule_based_understand("600519 适不适合我")
    assert out.goals[0].needs_profile is True
    assert out.goals[0].needs_account is True
