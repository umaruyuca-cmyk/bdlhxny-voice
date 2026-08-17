"""M7 退出门槛：第二 Domain 只能注册和复用，不能复制内核基础设施。"""

from __future__ import annotations

import ast
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "bdlh_runtime"
PROBE_ROOT = SRC_ROOT / "domains" / "plugin_probe"

FORBIDDEN_CLASS_NAMES = {
    "CapabilityRegistry",
    "ToolsetRegistry",
    "DomainBudget",
    "Observation",
    "GuardrailContext",
    "GuardrailResult",
    "TaskStore",
    "RunRegistry",
}

SHARED_CONTRACT_MODULES = {
    "bdlh_runtime.contracts.observation",
    "bdlh_runtime.domains.contracts",
    "bdlh_runtime.domains.manifests",
    "bdlh_runtime.tools.capabilities",
}

FORBIDDEN_IMPORT_PREFIXES = (
    "bdlh_runtime.domains.finance",
    "bdlh_runtime.integrations",
    "bdlh_runtime.memory",
    "bdlh_runtime.runtimes",
)


def probe_files() -> list[Path]:
    files = sorted(PROBE_ROOT.glob("*.py"))
    assert files, "M7 plugin probe package is missing"
    return files


def test_plugin_does_not_duplicate_shared_infrastructure_classes() -> None:
    declarations: set[str] = set()
    for file_path in probe_files():
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        declarations.update(
            node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        )

    assert not declarations & FORBIDDEN_CLASS_NAMES, (
        "M7 plugin duplicated shared infrastructure: "
        f"{sorted(declarations & FORBIDDEN_CLASS_NAMES)}"
    )


def test_plugin_has_no_finance_provider_memory_or_graph_dependency() -> None:
    imports: set[str] = set()
    for file_path in probe_files():
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)

    violations = sorted(
        module
        for module in imports
        for prefix in FORBIDDEN_IMPORT_PREFIXES
        if module == prefix or module.startswith(f"{prefix}.")
    )
    assert not violations, f"M7 plugin escaped its contract boundary: {violations}"


def test_plugin_imports_existing_shared_contracts_instead_of_redeclaring_them() -> None:
    imports: set[str] = set()
    for file_path in probe_files():
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)

    assert SHARED_CONTRACT_MODULES.issubset(imports), (
        "M7 plugin did not demonstrate reuse of all shared contracts: "
        f"missing={sorted(SHARED_CONTRACT_MODULES - imports)}"
    )


def test_domain_neutral_kernel_does_not_import_the_m7_plugin() -> None:
    targets = [
        SRC_ROOT / "cognitive",
        SRC_ROOT / "guardrails",
        SRC_ROOT / "observations",
        SRC_ROOT / "domains" / "contracts.py",
        SRC_ROOT / "domains" / "registry.py",
        SRC_ROOT / "domains" / "dispatcher.py",
    ]
    violations: list[str] = []
    for target in targets:
        files = sorted(target.rglob("*.py")) if target.is_dir() else [target]
        for file_path in files:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if "plugin_probe" in node.module:
                        violations.append(str(file_path.relative_to(SRC_ROOT)))
                elif isinstance(node, ast.Import):
                    if any("plugin_probe" in alias.name for alias in node.names):
                        violations.append(str(file_path.relative_to(SRC_ROOT)))
    assert not violations, f"domain-neutral kernel imports M7 plugin: {violations}"
