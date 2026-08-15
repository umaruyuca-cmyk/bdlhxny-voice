"""Toolset 派生视图回归：``SW31-TOOLSET-VIEW``。"""

from __future__ import annotations

import pytest

from bdlh_runtime.tools.capabilities import (
    CapabilityRegistry,
    CapabilitySpec,
    ToolsetName,
    build_default_capability_registry,
)
from bdlh_runtime.tools.toolsets import (
    ToolsetRegistry,
    build_default_toolset_registry,
)


def test_default_toolsets_cover_all_capabilities_without_copying_specs() -> None:
    capabilities = build_default_capability_registry()
    toolsets = build_default_toolset_registry(capabilities)

    grouped = [spec for toolset in toolsets.list() for spec in toolset.capabilities]

    assert toolsets.capability_registry is capabilities
    assert len(toolsets.list()) == 6
    # 15 = 14 个外部只读能力 + portfolio.build_current_valuation（M3 确定性重算能力）
    assert len(grouped) == 15
    assert {id(spec) for spec in grouped} == {id(spec) for spec in capabilities.list()}
    assert all(len(spec.toolsets) == 1 for spec in capabilities.list())


def test_default_toolset_membership_is_stable_and_business_facing() -> None:
    toolsets = build_default_toolset_registry()

    assert {
        toolset.name: len(toolset.capabilities)
        for toolset in toolsets.list()
    } == {
        ToolsetName.MARKET_READ: 4,
        ToolsetName.FUNDAMENTAL_READ: 3,
        ToolsetName.NEWS_READ: 2,
        # PORTFOLIO_READ 含 build_current_valuation（确定性重算，adapter=local）
        ToolsetName.PORTFOLIO_READ: 4,
        ToolsetName.FINANCIAL_PROFILE_READ: 1,
        ToolsetName.PLANNING_COMPUTE: 1,
    }


def test_selection_manifest_does_not_expand_all_capabilities() -> None:
    manifest = build_default_toolset_registry().selection_manifest()

    assert len(manifest) == 6
    assert all(set(item) == {"name", "description", "capability_count"} for item in manifest)
    assert all("mcp" not in str(item).lower() for item in manifest)


def test_selected_toolset_expands_only_safe_unified_capability_manifests() -> None:
    manifest = build_default_toolset_registry().capability_manifest(
        ToolsetName.NEWS_READ,
        analysis_type="fundamental",
    )

    assert {item["name"] for item in manifest} == {
        "market.get_news",
        "research.web_search",
    }
    assert all("adapter" not in item for item in manifest)
    assert all("server" not in item and "provider" not in item for item in manifest)


def test_suitability_toolsets_expose_only_the_three_minimum_user_reads() -> None:
    toolsets = build_default_toolset_registry()

    portfolio = toolsets.capability_manifest(
        ToolsetName.PORTFOLIO_READ,
        analysis_type="suitability",
    )
    profile = toolsets.capability_manifest(
        ToolsetName.FINANCIAL_PROFILE_READ,
        analysis_type="suitability",
    )

    assert {item["name"] for item in portfolio} == {
        "portfolio.get_current_positions",
        "portfolio.get_account_snapshot",
    }
    assert {item["name"] for item in profile} == {"user.get_risk_profile"}


def test_toolset_view_is_dynamic_over_the_single_capability_registry() -> None:
    capabilities = CapabilityRegistry()
    toolsets = ToolsetRegistry(capabilities)
    capabilities.register(
        CapabilitySpec(
            name="market.example_read",
            description="示例统一能力",
            domain="market",
            adapter="local",
            analysis_types=frozenset({"technical"}),
            toolsets=frozenset({ToolsetName.MARKET_READ}),
        )
    )

    assert [item.name for item in toolsets.get("market_read").capabilities] == [
        "market.example_read"
    ]


def test_toolset_registry_rejects_capabilities_without_group_membership() -> None:
    capabilities = CapabilityRegistry()
    capabilities.register(
        CapabilitySpec(
            name="market.ungrouped",
            description="未分组能力",
            domain="market",
            adapter="local",
            analysis_types=frozenset({"technical"}),
        )
    )

    with pytest.raises(ValueError, match="missing toolset membership"):
        ToolsetRegistry(capabilities).list()
