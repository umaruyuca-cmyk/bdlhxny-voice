"""Manifest 启动校验门禁（ADR-010 §3.1.2 fail-fast + ADR-009 §3.3 纯净度扩展）。

本测试镜像 ``test_kernel_purity.py`` 的风格，守护两件事：
  1. ADR-010 §3.1.2 的启动 fail-fast 规则在真实 finance descriptor + 真实
     Capability Registry 上必须通过；对伪造的不一致 descriptor 必须抛
     ``ConfigurationError``；
  2. ADR-009 §3.3 的纯净度扩展：``domains/manifests.py`` 是通用契约模型，
     不得 import 任何领域实现（finance）、Capability 实现或供应商适配——
     否则「换领域不用改内核」失效。
"""

from __future__ import annotations

import ast
from pathlib import Path
from dataclasses import replace

import pytest

from bdlh_runtime.domains.finance.contracts import FinancialIntent
from bdlh_runtime.domains.finance.manifests import (
    FINANCE_DESCRIPTOR,
    STOCK_RESEARCH_MANIFEST,
)
from bdlh_runtime.domains.manifests import DomainDescriptor, SkillManifest
from bdlh_runtime.runtime.errors import ConfigurationError
from bdlh_runtime.runtime.manifest_validation import (
    validate_descriptor_against_registry,
)
from tests.helpers_registry import build_default_capability_registry
from bdlh_runtime.tools.capabilities import (    CapabilityRegistry,
    CapabilitySpec,
    ToolsetName,)

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "bdlh_runtime"

# domains/manifests.py 禁止依赖的前缀（ADR-009 §3.3 扩展到新模块）
FORBIDDEN_MANIFEST_PREFIXES: tuple[str, ...] = (
    "bdlh_runtime.domains.finance",
    "bdlh_runtime.domain",
    "bdlh_runtime.integrations",
    "bdlh_runtime.tools",
)


# ── 启动校验：真实 descriptor 必须通过 ─────────────────────────────────────


def test_startup_validation_passes_for_current_finance_descriptor() -> None:
    """ADR-010 §6 验收①：真实 finance descriptor 对真实 Registry 校验通过。"""
    registry = build_default_capability_registry()
    # 不抛即通过
    validate_descriptor_against_registry(FINANCE_DESCRIPTOR, registry)


# ── 启动校验：不一致必须 fail-fast ──────────────────────────────────────────


def test_startup_validation_fails_on_missing_capability() -> None:
    """ADR-010 §3.1.2：manifest 引用未注册能力 → ConfigurationError。"""
    registry = build_default_capability_registry()
    # 构造一个引用不存在能力的 Skill
    bogus_skill = replace(
        STOCK_RESEARCH_MANIFEST,
        skill_id="bogus-skill",
        required_capabilities=frozenset({"market.does_not_exist"}),
    )
    bogus_descriptor = DomainDescriptor(
        domain="finance",
        descriptor_version="bogus",
        status="CURRENT",
        supported_intents=frozenset({FinancialIntent.STOCK_RESEARCH}),
        enabled_intents=frozenset({FinancialIntent.STOCK_RESEARCH}),
        skills=(bogus_skill,),
        request_contract="FinancialDomainRequest",
        outcome_contract="FinancialDomainOutcome",
    )
    with pytest.raises(ConfigurationError, match="unregistered capabilities"):
        validate_descriptor_against_registry(bogus_descriptor, registry)


def test_startup_validation_fails_on_unknown_toolset() -> None:
    """ADR-010 §3：required_toolsets 含非法 ToolsetName → ConfigurationError。"""
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
    """ADR-010 §3：v1 只读硬规则——side_effects 非空 → ConfigurationError。"""
    registry = build_default_capability_registry()
    bogus_skill = replace(
        STOCK_RESEARCH_MANIFEST,
        skill_id="bogus-write-skill",
        side_effects=frozenset({"writes_user_profile"}),
    )
    bogus_descriptor = _descriptor_with_single_skill(bogus_skill)
    with pytest.raises(ConfigurationError, match="side_effects"):
        validate_descriptor_against_registry(bogus_descriptor, registry)


def test_startup_validation_fails_on_enabled_intent_without_skill() -> None:
    """ADR-010 §5：enabled intent 无 Skill 声明处理 → ConfigurationError。"""
    registry = build_default_capability_registry()
    # SUITABILITY 被 enabled，但唯一 Skill 只声明处理 STOCK_RESEARCH
    bogus_descriptor = DomainDescriptor(
        domain="finance",
        descriptor_version="bogus",
        status="CURRENT",
        supported_intents=frozenset({
            FinancialIntent.STOCK_RESEARCH,
            FinancialIntent.SUITABILITY,
        }),
        enabled_intents=frozenset({FinancialIntent.SUITABILITY}),  # 无 Skill 声明
        skills=(STOCK_RESEARCH_MANIFEST,),
        request_contract="FinancialDomainRequest",
        outcome_contract="FinancialDomainOutcome",
    )
    with pytest.raises(ConfigurationError, match="没有任何 Skill"):
        validate_descriptor_against_registry(bogus_descriptor, registry)


def _descriptor_with_single_skill(skill: SkillManifest) -> DomainDescriptor:
    """用单个 Skill 构造一个最小 descriptor（intent 由该 skill 决定）。"""
    intent = next(iter(skill.accepted_intents))
    return DomainDescriptor(
        domain="finance",
        descriptor_version="bogus",
        status="CURRENT",
        supported_intents=frozenset({intent}),
        enabled_intents=frozenset({intent}),
        skills=(skill,),
        request_contract="FinancialDomainRequest",
        outcome_contract="FinancialDomainOutcome",
    )


# ── 纯净度扩展：domains/manifests.py 不得 import 领域/工具/适配 ─────────────


def _manifests_imported_modules() -> set[str]:
    """收集 domains/manifests.py 的全部 import 目标（含相对 import）。"""
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
            # 解析相对 import
            if node.level:
                package_parts = ["bdlh_runtime", "domains"]
                base = package_parts[: len(package_parts) - (node.level - 1)]
                if node.module:
                    base = [*base, *node.module.split(".")]
                modules.add(".".join(base))
    return modules


def test_manifests_module_remains_domain_agnostic() -> None:
    """ADR-009 §3.3 扩展：domains/manifests.py 是通用契约，不得依赖领域实现。

    若本测试失败，说明 manifest 模型层偷偷 import 了 finance/tools/integrations，
    「换领域不用改内核」当即失效。
    """
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
