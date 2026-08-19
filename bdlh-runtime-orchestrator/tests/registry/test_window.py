"""窗口与依赖闭包：低分/折叠不得从 allowed 删除能力（重写 §5）。"""

from __future__ import annotations

from bdlh_runtime.registry import (
    FLAT_WINDOW_LIMIT,
    CapabilityRecord,
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


def test_window_keeps_resolve_when_quote_allowed() -> None:
    """闭包带上 resolve；窗口可见能力包含 allowed 全集（含前置）。"""
    snapshot = _snapshot()
    ops = effective_operations(snapshot, account_id="*")
    allowed = allowed_capabilities(eligible_capabilities(snapshot, ops), authenticated=False)
    names = {cap.name for cap in allowed}
    assert "market.get_realtime_quote" in names
    assert "market.resolve_instrument" in names

    closure = dependency_closure(snapshot, ["market.get_realtime_quote"])
    assert "market.resolve_instrument" in closure

    window = build_window(snapshot, allowed)
    assert "market.resolve_instrument" in window.visible_capabilities
    assert set(window.visible_capabilities) == names


def test_folded_window_does_not_drop_allowed_capabilities() -> None:
    """n > FLAT_WINDOW_LIMIT 时折叠 toolset，但 visible_capabilities 仍等于 allowed。"""
    snapshot = _snapshot()
    ops = effective_operations(snapshot, account_id="*")
    base = allowed_capabilities(eligible_capabilities(snapshot, ops), authenticated=False)
    # 人为放大 allowed，触发折叠分支
    padded: list[CapabilityRecord] = list(base)
    for i in range(FLAT_WINDOW_LIMIT + 5 - len(base)):
        padded.append(
            CapabilityRecord(
                name=f"probe.extra_{i}",
                description="pad",
                domain="probe",
                adapter="local",
                read_only=True,
                requires_authenticated_user=False,
                required_arguments=frozenset(),
                depends_on=frozenset(),
                output_schema="Observation",
                timeout_seconds=5,
                cost=1,
                enabled=True,
                operations=frozenset({"RUN_ANALYSIS"}),
                toolsets=frozenset({"planning_compute"}),
            )
        )
    assert len(padded) > FLAT_WINDOW_LIMIT
    window = build_window(snapshot, padded)
    assert window.expansion_reason == "toolset_folded"
    assert set(window.visible_capabilities) == {cap.name for cap in padded}
    # 前置 resolve 仍在（不得因折叠从 allowed 消失）
    assert "market.resolve_instrument" in window.visible_capabilities
