"""Toolset 派生视图回归：``SW31-TOOLSET-VIEW``。"""

from __future__ import annotations

import pytest
from tests.helpers_registry import build_default_capability_registry, seeded_snapshot

from bdlh_runtime.tools.capabilities import (
    CapabilityRegistry,
    CapabilitySpec,
    ToolsetName,
)
from bdlh_runtime.tools.toolsets import (
    ToolsetRegistry,
    toolset_registry_from_snapshot,
)


def test_default_toolsets_cover_all_capabilities_without_copying_specs() -> None:
    capabilities = build_default_capability_registry()
    toolsets = toolset_registry_from_snapshot(seeded_snapshot())

    grouped = [spec for toolset in toolsets.list() for spec in toolset.capabilities]

    # 重写：目录与视图均来自同一 RegistrySnapshot（名字级一致即同源）
    assert sorted(c.name for c in toolsets.capability_registry.list()) == sorted(c.name for c in capabilities.list())
    assert len(toolsets.list()) == 7
    # 种子含 17 项能力（含 ADR-016 research.deep_search；M7 探针来自库表种子）。
    assert len(grouped) == 17
    assert all(len(spec.toolsets) == 1 for spec in capabilities.list())


def test_default_toolset_membership_is_stable_and_business_facing() -> None:
    toolsets = toolset_registry_from_snapshot(seeded_snapshot())

    assert {toolset.name: len(toolset.capabilities) for toolset in toolsets.list()} == {
        ToolsetName.MARKET_READ: 4,
        ToolsetName.FUNDAMENTAL_READ: 3,
        ToolsetName.NEWS_READ: 3,
        # PORTFOLIO_READ 含 build_current_valuation（确定性重算，adapter=local）
        ToolsetName.PORTFOLIO_READ: 4,
        ToolsetName.FINANCIAL_PROFILE_READ: 1,
        ToolsetName.PLANNING_COMPUTE: 1,
        ToolsetName.PLUGIN_PROBE_COMPUTE: 1,
    }


def test_selection_manifest_does_not_expand_all_capabilities() -> None:
    manifest = toolset_registry_from_snapshot(seeded_snapshot()).selection_manifest()

    assert len(manifest) == 7
    assert all(set(item) == {"name", "description", "capability_count"} for item in manifest)
    assert all("mcp" not in str(item).lower() for item in manifest)


def test_selected_toolset_expands_only_safe_unified_capability_manifests() -> None:
    manifest = toolset_registry_from_snapshot(seeded_snapshot()).capability_manifest(
        ToolsetName.NEWS_READ,
    )

    assert {item["name"] for item in manifest} == {
        "market.get_news",
        "research.web_search",
        "research.deep_search",
    }
    assert all("adapter" not in item for item in manifest)
    assert all("server" not in item and "provider" not in item for item in manifest)


def test_suitability_toolsets_expose_minimum_user_reads_and_local_valuation() -> None:
    toolsets = toolset_registry_from_snapshot(seeded_snapshot())

    portfolio = toolsets.capability_manifest(
        ToolsetName.PORTFOLIO_READ,
    )
    profile = toolsets.capability_manifest(
        ToolsetName.FINANCIAL_PROFILE_READ,
    )

    # 重写：组内展开不过滤（transaction_history 也在组；是否进菜单由资格决定）
    assert {item["name"] for item in portfolio} >= {
        "portfolio.get_current_positions",
        "portfolio.get_account_snapshot",
        "portfolio.build_current_valuation",
    }
    assert {item["name"] for item in profile} == {"user.get_risk_profile"}
    valuation = next(item for item in portfolio if item["name"] == "portfolio.build_current_valuation")
    assert "authenticated_user_id" not in valuation["required_arguments"]


def test_toolset_view_is_dynamic_over_the_single_capability_registry() -> None:
    """重写语义：视图从传入 Registry 现算，注册新能力后立即可见。"""
    capabilities = CapabilityRegistry()
    capabilities.register(
        CapabilitySpec(
            name="market.example_read",
            description="示例统一能力",
            domain="market",
            adapter="local",
            toolsets=frozenset({ToolsetName.MARKET_READ}),
        )
    )
    descriptions = {name.value: name.value for name in ToolsetName}
    toolsets = ToolsetRegistry(capabilities, descriptions)

    assert [item.name for item in toolsets.get("market_read").capabilities] == ["market.example_read"]


def test_toolset_registry_rejects_capabilities_without_group_membership() -> None:
    capabilities = CapabilityRegistry()
    capabilities.register(
        CapabilitySpec(
            name="market.ungrouped",
            description="未分组能力",
            domain="market",
            adapter="local",
        )
    )
    descriptions = {name.value: name.value for name in ToolsetName}

    with pytest.raises(ValueError, match="missing toolset membership"):
        ToolsetRegistry(capabilities, descriptions).list()
