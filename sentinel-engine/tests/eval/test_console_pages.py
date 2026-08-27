"""docs 站评测页面与真源同步守卫。

- 固定题库页（cases.html）必须覆盖 AB_CASES 全部题号与题目原文——题库改了页面没改即失败；
- 工具清单页（tools.html）必须覆盖工具目录全量工具名——目录增删工具页面未跟上即失败；
- 评测结果页（results.html）必须消费评测命令导出的 report.json。
"""

from __future__ import annotations

from pathlib import Path

from bdlh_runtime.registry import load_and_validate
from bdlh_runtime.tools.catalog import catalog_from_snapshot
from tests.eval.ab_eval import AB_CASES
from tests.registry.seeded_store import build_seeded_store

_CONSOLE_DOCS = Path(__file__).resolve().parents[3] / "sentinel-console" / "public" / "docs"


def test_cases_page_lists_all_eval_cases():
    html = (_CONSOLE_DOCS / "cases.html").read_text(encoding="utf-8")
    for case in AB_CASES:
        assert case.id in html, f"固定题库页缺少题号 {case.id}"
        assert case.message in html, f"固定题库页缺少题目原文 {case.id}：{case.message}"


def test_tools_page_lists_all_catalog_tools():
    html = (_CONSOLE_DOCS / "tools.html").read_text(encoding="utf-8")
    catalog = catalog_from_snapshot(load_and_validate(build_seeded_store()))
    names = sorted(card.name for card in catalog.list())
    assert names, "工具目录为空"
    for name in names:
        assert name in html, f"工具清单页缺少工具 {name}"


def test_results_page_consumes_report_json():
    html = (_CONSOLE_DOCS / "results.html").read_text(encoding="utf-8")
    assert "report.json" in html
    assert "tests.eval.ab_eval" in html
