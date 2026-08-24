"""PORTFOLIO_IMPACT / GOAL_PLANNING 的确定性影响构建（G8）。

只消费 FinancialSnapshot 与本轮 Observation 证据引用；不访问 Java/MCP/LLM，
不编造持仓权重或未确认目标。
"""

from __future__ import annotations

from bdlh_runtime.contracts.observation import Observation

from .contracts import (
    FinancialSnapshot,
    GoalImpact,
    PortfolioImpact,
)
from .snapshot_builder import PORTFOLIO_VALUATION_CAPABILITY


def build_portfolio_impact(snapshot: FinancialSnapshot) -> PortfolioImpact:
    """从快照持仓权重构建暴露面；无权重则返回空暴露并保留规则引用。"""
    current: dict[str, float] = {}
    by_symbol: dict[str, float] = {}
    by_industry: dict[str, float] = {}
    for position in snapshot.positions:
        if position.weight_pct is None:
            continue
        weight = float(position.weight_pct)
        symbol_key = f"symbol:{position.symbol}"
        by_symbol[symbol_key] = by_symbol.get(symbol_key, 0.0) + weight
        if position.industry:
            industry_key = f"industry:{position.industry}"
            by_industry[industry_key] = by_industry.get(industry_key, 0.0) + weight
    if by_symbol:
        top_symbol, top_weight = max(by_symbol.items(), key=lambda item: item[1])
        current["largest_position_weight_pct"] = round(top_weight, 4)
        current[top_symbol] = round(top_weight, 4)
    if by_industry:
        top_industry, top_industry_weight = max(by_industry.items(), key=lambda item: item[1])
        current["largest_industry_weight_pct"] = round(top_industry_weight, 4)
        current[top_industry] = round(top_industry_weight, 4)
    if snapshot.account and snapshot.account.cash is not None and snapshot.account.total_assets:
        total = float(snapshot.account.total_assets)
        if total > 0:
            current["cash_weight_pct"] = round(float(snapshot.account.cash) / total * 100, 4)
    return PortfolioImpact(
        current_exposure=current,
        projected_exposure={},
        rule_ids=["PORTFOLIO-EXPOSURE-001"],
    )


def build_goal_impact(snapshot: FinancialSnapshot) -> GoalImpact:
    """基于已确认目标与风险画像给出目标影响；无目标时明确 NONE + 原因。"""
    goals = list(snapshot.goals)
    if not goals:
        return GoalImpact(
            affected_goal_ids=[],
            impact_level="NONE",
            reasons=["未提供已确认投资目标，无法评估目标规划影响"],
        )
    level = "LOW"
    reasons: list[str] = [f"已纳入 {len(goals)} 个已确认目标"]
    risk = snapshot.risk_profile.risk_level if snapshot.risk_profile else None
    short_term = [goal for goal in goals if goal.horizon == "SHORT_TERM"]
    if short_term and risk == "AGGRESSIVE":
        level = "HIGH"
        reasons.append("存在短期目标且风险偏好偏进取，期限与风险张力较高")
    elif short_term and risk == "BALANCED":
        level = "MEDIUM"
        reasons.append("存在短期目标，需确认期限与风险偏好是否匹配")
    elif short_term:
        level = "MEDIUM"
        reasons.append("存在短期目标，需结合可承受回撤与流动性再确认")
    largest = None
    for position in snapshot.positions:
        if position.weight_pct is None:
            continue
        if largest is None or position.weight_pct > largest:
            largest = float(position.weight_pct)
    if largest is not None and largest >= 40 and level in {"LOW", "MEDIUM"}:
        level = "MEDIUM" if level == "LOW" else "HIGH"
        reasons.append(f"单一持仓权重约 {largest:.1f}%，可能影响目标兑现路径")
    return GoalImpact(
        affected_goal_ids=[goal.goal_id for goal in goals],
        impact_level=level,  # type: ignore[arg-type]
        reasons=reasons,
    )


def impact_evidence_refs(snapshot: FinancialSnapshot, observations: list[Observation]) -> list[str]:
    """证据链：快照 provenance ∪ 本轮估值 Observation。"""
    refs = list(dict.fromkeys(snapshot.provenance))
    for item in observations:
        if item.capability == PORTFOLIO_VALUATION_CAPABILITY and item.observation_id not in refs:
            refs.append(item.observation_id)
    if not refs:
        refs = [f"request-user:{snapshot.user_id}"]
    return refs
