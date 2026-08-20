"""内核纯净度门禁：ADR-009 §3.3。

产品身份是通用 Agent Runtime，金融只是第一个 Domain Skill。因此认知层、
领域调度层、治理层和观察层必须对具体领域零依赖，否则「换领域不用改内核」
只是文档说法。本测试用 AST 静态检查 import，能同时覆盖模块级 import 和
函数体内的延迟 import。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "bdlh_runtime"

# 1. 受管内核模块：ADR-009 §3.3 列出的清单，目录项递归展开
KERNEL_TARGETS: tuple[str, ...] = (
    "cognitive",
    "domains/contracts.py",
    "domains/registry.py",
    "guardrails",
    "observations",
)

# 2. 禁止被内核依赖的领域模块前缀（相对包路径）
FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "bdlh_runtime.domains.finance",
    "bdlh_runtime.domain",  # 金融确定性计算引擎
    "bdlh_runtime.integrations",  # 供应商适配
    "bdlh_runtime.tools",  # Capability 实现与 Adapter 路由
)


def _kernel_files() -> list[Path]:
    """展开受管清单为具体 .py 文件列表。"""
    files: list[Path] = []
    for target in KERNEL_TARGETS:
        path = SRC_ROOT / target
        if path.is_dir():
            files.extend(sorted(path.rglob("*.py")))
        else:
            assert path.is_file(), f"内核清单中的文件不存在：{path}"
            files.append(path)
    assert files, "内核文件清单为空，说明目录结构已变化，必须同步更新本测试与 ADR-009"
    return files


def _imported_modules(tree: ast.AST) -> set[str]:
    """收集一个模块中出现的全部 import 目标（含相对 import 的显式部分）。"""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            # level > 0 是包内相对 import；这里只需判断显式写出的模块名
            modules.add(node.module)
    return modules


def _relative_import_targets(tree: ast.AST, file_path: Path) -> set[str]:
    """把相对 import 解析为绝对包路径，避免 `from ..domain import x` 逃过检查。"""
    package_parts = ["bdlh_runtime", *file_path.relative_to(SRC_ROOT).parts[:-1]]
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            # level=1 表示当前包，level=2 表示上一级，依次类推
            base = package_parts[: len(package_parts) - (node.level - 1)]
            if node.module:
                base = [*base, *node.module.split(".")]
            targets.add(".".join(base))
    return targets


@pytest.mark.parametrize("kernel_file", _kernel_files(), ids=lambda p: p.name)
def test_kernel_module_does_not_import_domain(kernel_file: Path):
    """内核模块不得 import 领域实现、确定性引擎、供应商适配或 Capability 实现。"""
    tree = ast.parse(kernel_file.read_text(encoding="utf-8"))
    imported = _imported_modules(tree) | _relative_import_targets(tree, kernel_file)

    violations = sorted(
        module
        for module in imported
        for prefix in FORBIDDEN_PREFIXES
        if module == prefix or module.startswith(f"{prefix}.")
    )
    assert not violations, (
        f"{kernel_file.relative_to(SRC_ROOT)} 违反 ADR-009 §3.3 内核纯净度："
        f"不得依赖 {violations}。领域语义只能经通用 DomainRequest / DomainOutcome 传递。"
    )


def test_cognitive_only_depends_on_generic_domain_contracts():
    """认知层与领域的唯一接触面必须是通用 domains.contracts。"""
    cognitive_files = sorted((SRC_ROOT / "cognitive").rglob("*.py"))
    assert cognitive_files, "cognitive 包为空，目录结构已变化"

    domain_imports: set[str] = set()
    for file_path in cognitive_files:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        imported = _imported_modules(tree) | _relative_import_targets(tree, file_path)
        domain_imports |= {module for module in imported if module.startswith("bdlh_runtime.domains")}

    assert domain_imports == {"bdlh_runtime.domains.contracts"}, (
        f"认知层只允许依赖 bdlh_runtime.domains.contracts，实际为 {sorted(domain_imports)}"
    )
