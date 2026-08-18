"""GoalCoverage 判定测试：OR 语义 / 无 topic / 账户 Goal 隔离 / 降级兜底隔离。"""

from __future__ import annotations

from bdlh_runtime.cognitive.goal_coverage import (
    all_goals_settled,
    backfill_criteria,
    evaluate_goals,
)
from bdlh_runtime.cognitive.goal_schema import GoalSpec, SuccessCriterion
from bdlh_runtime.registry import load_and_validate

from ..registry.seeded_store import build_seeded_store

SNAPSHOT = load_and_validate(build_seeded_store())
DEFAULT_ALLOWED = [
    "market.resolve_instrument", "market.get_realtime_quote",
    "market.get_historical_prices", "market.get_financial_statements",
    "market.get_valuation", "market.get_industry_context",
    "market.get_money_flow", "market.get_news",
    "research.web_search", "analysis.run_analysis",
]


def _obs(capability: str, obs_id: str, status: str = "SUCCESS") -> dict:
    return {
        "observation_id": obs_id,
        "capability": capability,
        "status": status,
        "data": {"sample": True} if status != "FAILED" else None,
    }


def _goal(**kwargs) -> GoalSpec:
    defaults = dict(
        goal_id="g1",
        objective="objective",
        success_criteria=[SuccessCriterion(criterion_id="c1", description="c")],
    )
    defaults.update(kwargs)
    return GoalSpec(**defaults)


def test_topic_or_semantics_one_provider_down_still_covered() -> None:
    """news 主题：get_news 失败但 web_search 成功 → 仍 COVERED，不 BLOCKED。"""
    goal = _goal(
        success_criteria=[SuccessCriterion(criterion_id="c1", topic="news", description="新闻")]
    )
    goals = backfill_criteria(SNAPSHOT, [goal], DEFAULT_ALLOWED)
    observations = [
        _obs("market.resolve_instrument", "o-resolve"),
        _obs("market.get_news", "o-news", status="FAILED"),
        _obs("research.web_search", "o-web"),
    ]
    result = evaluate_goals(goals, observations, DEFAULT_ALLOWED, SNAPSHOT)
    assert result[0].status == "COVERED"
    assert "o-web" in result[0].observation_refs


def test_no_topic_resolve_alone_stays_pending() -> None:
    """无 topic：仅 resolve 成功、无业务数据 Observation → PENDING，FINISH 被拒。"""
    goal = _goal()
    goals = backfill_criteria(SNAPSHOT, [goal], DEFAULT_ALLOWED)
    observations = [_obs("market.resolve_instrument", "o-resolve")]
    result = evaluate_goals(goals, observations, DEFAULT_ALLOWED, SNAPSHOT)
    assert result[0].status == "PENDING"
    assert not all_goals_settled(result)


def test_no_topic_quote_covers() -> None:
    """无 topic：quote（非纯 resolve 业务数据）成功 → COVERED。"""
    goal = _goal()
    goals = backfill_criteria(SNAPSHOT, [goal], DEFAULT_ALLOWED)
    observations = [
        _obs("market.resolve_instrument", "o-resolve"),
        _obs("market.get_realtime_quote", "o-quote"),
    ]
    result = evaluate_goals(goals, observations, DEFAULT_ALLOWED, SNAPSHOT)
    assert result[0].status == "COVERED"


def test_account_goal_without_entitlement_is_blocked() -> None:
    """needs_account 且无持仓证 → BLOCKED，不编数据。"""
    goal = _goal(needs_account=True)
    goals = backfill_criteria(SNAPSHOT, [goal], DEFAULT_ALLOWED)
    result = evaluate_goals(goals, [], DEFAULT_ALLOWED, SNAPSHOT)
    assert result[0].status == "BLOCKED"


def test_account_goal_quote_cannot_cover() -> None:
    """有持仓证时：市场 quote 不能顶账户 Goal——须 portfolio.* Observation。"""
    allowed = DEFAULT_ALLOWED + ["portfolio.get_current_positions"]
    goal = _goal(needs_account=True)
    goals = backfill_criteria(SNAPSHOT, [goal], allowed)
    observations = [
        _obs("market.resolve_instrument", "o-resolve"),
        _obs("market.get_realtime_quote", "o-quote"),
    ]
    result = evaluate_goals(goals, observations, allowed, SNAPSHOT)
    assert result[0].status == "PENDING"  # quote 不顶账户 Goal
    observations.append(_obs("portfolio.get_current_positions", "o-pos"))
    result = evaluate_goals(goals, observations, allowed, SNAPSHOT)
    assert result[0].status == "COVERED"
    assert "o-pos" in result[0].observation_refs


def test_money_flow_topic_quote_does_not_cover() -> None:
    """闭包不进 OR：money_flow 主题下 quote 成功不构成资金流覆盖。"""
    goal = _goal(
        success_criteria=[SuccessCriterion(criterion_id="c1", topic="money_flow", description="资金流")]
    )
    goals = backfill_criteria(SNAPSHOT, [goal], DEFAULT_ALLOWED)
    observations = [
        _obs("market.resolve_instrument", "o-resolve"),
        _obs("market.get_realtime_quote", "o-quote"),
    ]
    result = evaluate_goals(goals, observations, DEFAULT_ALLOWED, SNAPSHOT)
    assert result[0].status == "PENDING"
    observations.append(_obs("market.get_money_flow", "o-flow"))
    result = evaluate_goals(goals, observations, DEFAULT_ALLOWED, SNAPSHOT)
    assert result[0].status == "COVERED"


def test_rule_based_fallback_is_isolated() -> None:
    """降级兜底（任一非空 Observation 即 COVERED）只在显式开启时生效。"""
    goal = _goal()
    goals = backfill_criteria(SNAPSHOT, [goal], DEFAULT_ALLOWED)
    observations = [_obs("market.resolve_instrument", "o-resolve")]
    strict = evaluate_goals(goals, observations, DEFAULT_ALLOWED, SNAPSHOT)
    assert strict[0].status == "PENDING"
    fallback = evaluate_goals(
        goals, observations, DEFAULT_ALLOWED, SNAPSHOT, rule_based_fallback=True
    )
    assert fallback[0].status == "COVERED"


def test_finish_gate_requires_all_settled() -> None:
    """复合 Goal：一个 COVERED 一个 PENDING → FINISH 不被接受。"""
    goals = [
        _goal(goal_id="g1"),
        _goal(goal_id="g2", needs_account=True),
    ]
    goals = backfill_criteria(SNAPSHOT, goals, DEFAULT_ALLOWED)
    observations = [
        _obs("market.resolve_instrument", "o-resolve"),
        _obs("market.get_realtime_quote", "o-quote"),
    ]
    result = evaluate_goals(goals, observations, DEFAULT_ALLOWED, SNAPSHOT)
    statuses = {goal.goal_id: goal.status for goal in result}
    assert statuses["g1"] == "COVERED"
    assert statuses["g2"] == "BLOCKED"
    assert all_goals_settled(result)
