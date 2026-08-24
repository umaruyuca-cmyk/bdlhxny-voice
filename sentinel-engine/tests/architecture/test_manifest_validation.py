"""Manifest 启动校验门禁（ADR-010 fail-fast + ADR-009 §3.3 纯净度）。"""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest
from tests.helpers_registry import build_default_capability_registry, seeded_snapshot

from bdlh_runtime.domains.finance.manifests import build_finance_descriptor
from bdlh_runtime.domains.manifests import DomainDescriptor, SkillManifest
from bdlh_runtime.infra.errors import ConfigurationError
from bdlh_runtime.infra.manifest_validation import (
    validate_descriptor_against_registry,
)

STOCK_RESEARCH_MANIFEST = next(
    s for s in build_finance_descriptor(seeded_snapshot()).skills if s.skill_id == "stock-research"
)

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "bdlh_runtime"

FORBIDDEN_MANIFEST_PREFIXES: tuple[str, ...] = (
    "bdlh_runtime.domains.finance",
    "bdlh_runtime.compute",
    "bdlh_runtime.integrations",
    "bdlh_runtime.tools",
)


def test_startup_validation_passes_for_current_finance_descriptor() -> None:
    registry = build_default_capability_registry()
    validate_descriptor_against_registry(build_finance_descriptor(seeded_snapshot()), registry)


def test_startup_validation_fails_on_missing_capability() -> None:
    registry = build_default_capability_registry()
    bogus_skill = replace(
        STOCK_RESEARCH_MANIFEST,
        skill_id="bogus-skill",
        required_capabilities=frozenset({"market.does_not_exist"}),
    )
    bogus_descriptor = DomainDescriptor(
        domain="finance",
        descriptor_version="bogus",
        status="CURRENT",
        skills=(bogus_skill,),
        request_contract="FinancialDomainRequest",
        outcome_contract="FinancialDomainOutcome",
    )
    with pytest.raises(ConfigurationError, match="unregistered capabilities"):
        validate_descriptor_against_registry(bogus_descriptor, registry)


def test_startup_validation_fails_on_unknown_toolset() -> None:
    registry = build_default_capability_registry()
    bogus_skill = replace(
        STOCK_RESEARCH_MANIFEST,
        skill_id="bogus-toolset-skill",
        required_toolsets=frozenset({"nonexistent_toolset"}),
    )
    bogus_descriptor = _descriptor_with_single_skill(bogus_skill)
    with pytest.raises(ConfigurationError, match="unknown toolsets"):
        validate_descriptor_against_registry(bogus_descriptor, registry)


def test_startup_validation_fails_on_non_empty_side_effects() -> None:
    registry = build_default_capability_registry()
    bogus_skill = replace(
        STOCK_RESEARCH_MANIFEST,
        skill_id="bogus-write-skill",
        side_effects=frozenset({"writes_user_profile"}),
    )
    bogus_descriptor = _descriptor_with_single_skill(bogus_skill)
    with pytest.raises(ConfigurationError, match="side_effects"):
        validate_descriptor_against_registry(bogus_descriptor, registry)


def _descriptor_with_single_skill(skill: SkillManifest) -> DomainDescriptor:
    return DomainDescriptor(
        domain="finance",
        descriptor_version="bogus",
        status="CURRENT",
        skills=(skill,),
        request_contract="FinancialDomainRequest",
        outcome_contract="FinancialDomainOutcome",
    )


def _manifests_imported_modules() -> set[str]:
    manifests_file = SRC_ROOT / "domains" / "manifests.py"
    assert manifests_file.is_file(), f"内核契约文件不存在：{manifests_file}"
    tree = ast.parse(manifests_file.read_text(encoding="utf-8"))

    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
            if node.level:
                package_parts = ["bdlh_runtime", "domains"]
                base = package_parts[: len(package_parts) - (node.level - 1)]
                if node.module:
                    base = [*base, *node.module.split(".")]
                modules.add(".".join(base))
    return modules


def test_manifests_module_remains_domain_agnostic() -> None:
    imported = _manifests_imported_modules()
    violations = sorted(
        module
        for module in imported
        for prefix in FORBIDDEN_MANIFEST_PREFIXES
        if module == prefix or module.startswith(f"{prefix}.")
    )
    assert not violations, (
        "domains/manifests.py 违反 ADR-009 §3.3 内核纯净度（扩展到 manifest 模型层）："
        f"不得依赖 {violations}。manifest 只允许引用 domains.contracts 的通用类型。"
    )
