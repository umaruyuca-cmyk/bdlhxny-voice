"""菜单算法测试：effective_operations / eligible / allowed / 闭包。"""

from __future__ import annotations

from dataclasses import replace

from bdlh_runtime.registry import (
    DEFAULT_ENTITLEMENT_OPERATIONS,
    DEFAULT_RUNTIME_ALLOWED_OPERATIONS,
    allowed_capabilities,
    dependency_closure,
    effective_operations,
    eligible_capabilities,
    load_and_validate,
)

from .seeded_store import build_seeded_store


def _snapshot():
    return load_and_validate(build_seeded_store())


def test_optional_operations_merge_into_effective() -> None:
    """skill 的 optional 行并入 effective_operations。"""
    snapshot = _snapshot()
    ops = effective_operations(snapshot)
    assert "READ_PUBLIC_RESEARCH" in ops
    assert "READ_PORTFOLIO" in ops
    assert "READ_PROFILE" in ops
    assert ops == {
        "READ_MARKET_DATA",
        "READ_PUBLIC_RESEARCH",
        "READ_PORTFOLIO",
        "READ_PROFILE",
        "READ_FINANCIAL_GOALS",
        "RUN_ANALYSIS",
    }


def test_default_menu_includes_portfolio_when_authenticated() -> None:
    """G8：portfolio-health 默认启用；登录后 allowed 含 portfolio.*。"""
    snapshot = _snapshot()
    ops = effective_operations(snapshot)
    eligible = eligible_capabilities(snapshot, ops)
    anon = {cap.name for cap in allowed_capabilities(eligible, authenticated=False)}
    authed = {cap.name for cap in allowed_capabilities(eligible, authenticated=True)}
    assert "market.get_realtime_quote" in anon
    assert "portfolio.get_current_positions" not in anon
    assert "portfolio.get_current_positions" in authed
    assert "portfolio.build_current_valuation" in authed
    assert "user.get_risk_profile" in authed


def test_login_adds_authenticated_portfolio_caps() -> None:
    """登录把 requires_authenticated_user 的能力放入 allowed。"""
    snapshot = _snapshot()
    ops = effective_operations(snapshot)
    eligible = eligible_capabilities(snapshot, ops)
    eligible_names = {cap.name for cap in eligible}
    assert any(name.startswith("portfolio.") for name in eligible_names)
    allowed = {cap.name for cap in allowed_capabilities(eligible, authenticated=True)}
    assert "portfolio.get_current_positions" in allowed
    assert allowed == eligible_names


def test_portfolio_requires_skill_entitlement_and_login() -> None:
    """启用 portfolio-health + READ_PORTFOLIO entitlement + 登录 → 持仓进 allowed。"""
    store = build_seeded_store()
    store.skills = [
        replace(skill, enabled=True) if skill.skill_id == "portfolio-health" else skill for skill in store.skills
    ]
    snapshot = load_and_validate(store)
    entitlement = frozenset(DEFAULT_ENTITLEMENT_OPERATIONS | {"READ_PORTFOLIO", "READ_PROFILE"})
    ops = effective_operations(
        snapshot,
        runtime_allowed=DEFAULT_RUNTIME_ALLOWED_OPERATIONS,
        entitlement=entitlement,
    )
    eligible = eligible_capabilities(snapshot, ops)
    anon = {cap.name for cap in allowed_capabilities(eligible, authenticated=False)}
    authed = {cap.name for cap in allowed_capabilities(eligible, authenticated=True)}
    assert "portfolio.get_current_positions" not in anon
    assert "portfolio.get_current_positions" in authed
    assert "portfolio.build_current_valuation" in authed


def test_local_capability_enters_eligible_via_skill() -> None:
    """local 能力（build_current_valuation）经 skill 声明进入 eligible。"""
    store = build_seeded_store()
    store.skills = [
        replace(skill, enabled=True) if skill.skill_id == "portfolio-health" else skill for skill in store.skills
    ]
    snapshot = load_and_validate(store)
    entitlement = frozenset(DEFAULT_ENTITLEMENT_OPERATIONS | {"READ_PORTFOLIO", "READ_PROFILE"})
    ops = effective_operations(snapshot, entitlement=entitlement)
    eligible = {cap.name for cap in eligible_capabilities(snapshot, ops)}
    assert "portfolio.build_current_valuation" in eligible
    anon = {
        cap.name
        for cap in allowed_capabilities(
            [cap for cap in snapshot.capabilities if cap.name in eligible],
            authenticated=False,
        )
    }
    assert "portfolio.build_current_valuation" not in anon


def test_dependency_closure_includes_resolve() -> None:
    """闭包带上 resolve：暴露 quote 时 resolve 一并可见。"""
    snapshot = _snapshot()
    closure = dependency_closure(snapshot, ["market.get_realtime_quote"])
    assert "market.resolve_instrument" in closure
    assert set(closure) == {"market.get_realtime_quote", "market.resolve_instrument"}


def test_utterance_and_topics_do_not_change_eligible() -> None:
    """eligible 不读取用户原句或 requested_topics。"""
    snapshot = _snapshot()
    baseline = {cap.name for cap in eligible_capabilities(snapshot, effective_operations(snapshot))}
    # 调用签名无 utterance/topics 参数；重复计算应完全一致
    again = {cap.name for cap in eligible_capabilities(snapshot, effective_operations(snapshot))}
    assert baseline == again
