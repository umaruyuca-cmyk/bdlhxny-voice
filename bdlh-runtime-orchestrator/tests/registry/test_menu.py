"""菜单算法测试：effective_operations / eligible / allowed / 闭包（重写 §5）。"""

from __future__ import annotations

from dataclasses import replace

from bdlh_runtime.registry import (
    EntitlementRecord,
    allowed_capabilities,
    build_window,
    dependency_closure,
    effective_operations,
    eligible_capabilities,
    load_and_validate,
)

from .seeded_store import build_seeded_store


def _snapshot():
    return load_and_validate(build_seeded_store())


def test_optional_operations_merge_into_effective() -> None:
    """skill 的 optional 行并入 effective_operations——只并 required 是 bug：
    READ_PUBLIC_RESEARCH 进不了有效证，web_search 永远进不了菜单。"""
    snapshot = _snapshot()
    ops = effective_operations(snapshot, account_id="*")
    assert "READ_PUBLIC_RESEARCH" in ops  # stock-research 的 optional 证生效
    assert ops == {"READ_MARKET_DATA", "READ_PUBLIC_RESEARCH", "RUN_ANALYSIS"}


def test_default_menu_has_no_portfolio_but_has_market() -> None:
    """默认用户（只开 stock-research）：allowed 含行情/估值，不含 portfolio.*。"""
    snapshot = _snapshot()
    ops = effective_operations(snapshot, account_id="*")
    eligible = eligible_capabilities(snapshot, ops)
    names = {cap.name for cap in allowed_capabilities(eligible, authenticated=False)}
    assert "market.get_realtime_quote" in names
    assert "market.get_historical_prices" in names
    assert "market.get_valuation" in names
    assert "research.web_search" in names
    assert not any(name.startswith("portfolio.") for name in names)
    assert "user.get_risk_profile" not in names


def test_login_does_not_change_eligible() -> None:
    """登录不产生 entitlement，只把 requires_authenticated_user 的能力放入 allowed。"""
    snapshot = _snapshot()
    ops = effective_operations(snapshot, account_id="*")
    eligible = eligible_capabilities(snapshot, ops)
    eligible_names = {cap.name for cap in eligible}
    # 默认 entitlement 不含 READ_PORTFOLIO：持仓能力不在 eligible，与登录无关
    assert not any(name.startswith("portfolio.") for name in eligible_names)
    allowed = {cap.name for cap in allowed_capabilities(eligible, authenticated=True)}
    assert allowed == eligible_names  # 无需认证的能力：登录不增不减


def test_portfolio_requires_skill_entitlement_and_login() -> None:
    """启用 portfolio-health + READ_PORTFOLIO entitlement + 登录 → 持仓进 allowed。"""
    store = build_seeded_store()
    store.skills = [
        replace(skill, enabled=True) if skill.skill_id == "portfolio-health" else skill
        for skill in store.skills
    ]
    store.entitlements = list(store.entitlements) + [
        EntitlementRecord(account_id="*", operation_code="READ_PORTFOLIO"),
        EntitlementRecord(account_id="*", operation_code="READ_PROFILE"),
    ]
    snapshot = load_and_validate(store)
    ops = effective_operations(snapshot, account_id="*")
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
        replace(skill, enabled=True) if skill.skill_id == "portfolio-health" else skill
        for skill in store.skills
    ]
    store.entitlements = list(store.entitlements) + [
        EntitlementRecord(account_id="*", operation_code="READ_PORTFOLIO"),
        EntitlementRecord(account_id="*", operation_code="READ_PROFILE"),
    ]
    snapshot = load_and_validate(store)
    ops = effective_operations(snapshot, account_id="*")
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
    """闭包带上 resolve：暴露 quote 时 resolve 一并可见（不进 OR 集合）。"""
    snapshot = _snapshot()
    closure = dependency_closure(snapshot, ["market.get_realtime_quote"])
    assert "market.resolve_instrument" in closure
    assert set(closure) == {"market.get_realtime_quote", "market.resolve_instrument"}


def test_flat_window_when_small() -> None:
    """n <= 20 时窗口扁平列出全部 allowed。"""
    snapshot = _snapshot()
    ops = effective_operations(snapshot, account_id="*")
    allowed = allowed_capabilities(eligible_capabilities(snapshot, ops), authenticated=False)
    window = build_window(snapshot, allowed)
    assert window.visible_capabilities == sorted(cap.name for cap in allowed)
    assert window.expansion_reason == "flat"
