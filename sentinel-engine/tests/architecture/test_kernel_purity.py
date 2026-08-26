"""引擎内核纯净度门禁（设计文档 §3.2、§3.3）。

引擎内核（``engine`` / ``guardrails`` / ``observations``）对金融确定性计算
（``compute/``）与供应商适配（``integrations/``）零依赖；具体工具实现
（``tools/`` 下的 adapter / capability / deep_research 等）也不得被内核直接
依赖，领域语义只能经通用契约（``engine.contracts``）传递。工具目录
（``tools.catalog``）与检索索引（``tools.search``）是引擎的合法接口依赖，
不在此限。

本测试用 AST 静态检查 import，能同时覆盖模块级 import 和函数体内的延迟 import。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "bdlh_runtime"

# 1. 受管内核模块：设计文档 §3.3 组件职责表中的引擎内核三件套
KERNEL_TARGETS: tuple[str, ...] = (
    "engine",
    "guardrails",
    "observations",
)

# 2. 禁止被内核依赖的模块前缀（相对包路径）
FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "bdlh_runtime.compute",  # 金融确定性计算引擎
    "bdlh_runtime.integrations",  # 供应商适配（MCP 等）
    # 具体工具实现：引擎只读目录（catalog/search），不直接依赖实现
    "bdlh_runtime.tools.capabilities",
    "bdlh_runtime.tools.coverage",
    "bdlh_runtime.tools.java_data_adapter",
    "bdlh_runtime.tools.web_search_adapter",
    "bdlh_runtime.tools.analysis_capability",
    "bdlh_runtime.tools.deep_research",
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
    assert files, "内核文件清单为空，说明目录结构已变化，必须同步更新本测试"
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
    """把相对 import 解析为绝对包路径，避免 `from ..compute import x` 逃过检查。"""
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
    """内核模块不得 import 金融确定性计算、供应商适配或具体工具实现。

    领域语义只能经通用 ``DomainRequest`` / ``DomainOperation`` 传递
    （设计文档 §3.2：能力接入标准化，对引擎透明）。
    """
    tree = ast.parse(kernel_file.read_text(encoding="utf-8"))
    imported = _imported_modules(tree) | _relative_import_targets(tree, kernel_file)

    violations = sorted(
        module
        for module in imported
        for prefix in FORBIDDEN_PREFIXES
        if module == prefix or module.startswith(f"{prefix}.")
    )
    assert not violations, (
        f"{kernel_file.relative_to(SRC_ROOT)} 违反内核纯净度："
        f"不得依赖 {violations}。领域语义只能经通用契约传递。"
    )
