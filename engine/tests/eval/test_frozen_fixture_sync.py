"""冻结工具返回种子同步守卫。

数据库 init.sql 的冻结数据段是 ``fixture_tool_responses`` 的唯一真源；单测注入的
``tests/eval/frozen_fixtures.py`` payload 是替身。两者漂移（改了一处忘另一处）即失败。

GT-2 起 ab-eval 集的增量行经 ``db/postgresql/changes/`` 脚本交付（不回改 init.sql），
守卫按 init.sql → changes/*.sql（文件名序）拼接提取，镜像需与两者合并结果一致。
GT-3 起负例集（ab-eval-negative-v1）与正例集同表存放：ab-eval 行仍须全 SUCCESS
（FrozenObservations 的正例集语义），负例集行按 (call_key, tool_name, status)
同序镜像同步，不做全 SUCCESS 断言。失败档用 ERROR（schema CHECK 只允许
SUCCESS/TIMEOUT/ERROR/DENIED；FAILED 是引擎侧失败桩词汇，不进库）。
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.eval.frozen_fixtures import FROZEN_RESPONSES, NEGATIVE_RESPONSES

_REPO = Path(__file__).resolve().parents[3]
_SEED_SQL = _REPO / "db" / "postgresql" / "setup" / "init.sql"
_CHANGES_DIR = _REPO / "db" / "postgresql" / "changes"


def _fixture_sections() -> list[str]:
    """所有 ``INSERT INTO fixture_tool_responses`` 语句段:init.sql + changes/*.sql(文件名序)。"""
    texts = []

    def section_of(content: str) -> str:
        start = content.index("INSERT INTO touchstone.fixture_tool_responses")
        return content[start : content.index(";", start)]

    texts.append(section_of(_SEED_SQL.read_text(encoding="utf-8")))
    for script in sorted(_CHANGES_DIR.glob("*.sql")):
        content = script.read_text(encoding="utf-8")
        if "INSERT INTO touchstone.fixture_tool_responses" in content:
            texts.append(section_of(content))
    return texts


def _rows(fixture_set_id: str) -> list[tuple[str, str, str]]:
    """按 sequence 顺序提取 (call_key, tool_name, response_status) 行。

    每行以行首 ``('<set_id>', <version>,`` 开始,按行块切分后匹配;
    其他集名的行（如负例集）不会误匹配。
    """
    prefix = re.compile(rf"^\('{re.escape(fixture_set_id)}', \d+, '([^']+)', '([^']+)'")
    rows: list[tuple[str, str, str]] = []
    for text in _fixture_sections():
        for chunk in re.split(r"(?=^\()", text, flags=re.MULTILINE):
            matched = prefix.match(chunk)
            if not matched:
                continue
            status = re.search(r"'(SUCCESS|FAILED|ERROR|TIMEOUT)'", chunk)
            rows.append((matched.group(1), matched.group(2), status.group(1) if status else "?"))
    return rows


def test_frozen_fixture_rows_match_seed_in_order():
    assert _rows("ab-eval") == [(key, tool, "SUCCESS") for key, tool, _ in FROZEN_RESPONSES], (
        "ab-eval 冻结返回清单与数据库 seed(init.sql + changes/) 不一致（含顺序，即 sequence 语义）"
    )


def test_frozen_lookup_rows_are_all_success():
    """ab-eval 冻结集语义不变:全部 SUCCESS(负例请落 ab-eval-negative-v1 等独立冻结集)。"""
    statuses = {status for _key, _tool, status in _rows("ab-eval")}
    assert statuses == {"SUCCESS"}, "ab-eval 集出现非 SUCCESS 行,需同步调整替身与查找语义"


def test_negative_fixture_rows_match_seed_in_order():
    """负例集镜像同步:(call_key, tool_name, status) 与 changes SQL 逐行一致。"""
    assert _rows("ab-eval-negative-v1") == [
        (key, tool, status) for key, tool, status, _response in NEGATIVE_RESPONSES
    ], "ab-eval-negative-v1 冻结返回清单与 changes/20260822-fixture-negative.sql 不一致"


def test_negative_set_covers_all_kinds_for_symbol_tools():
    """审计结论的守卫:8 个 symbol 型工具 × {空结果, FAILED, TIMEOUT} 全档覆盖。"""
    symbol_tools = {
        "market.resolve_instrument",
        "market.get_realtime_quote",
        "market.get_valuation",
        "market.get_financial_statements",
        "market.get_historical_prices",
        "market.get_industry_context",
        "market.get_news",
        "market.get_money_flow",
    }
    by_tool: dict[str, set[str]] = {tool: set() for tool in symbol_tools}
    for key, tool, status in _rows("ab-eval-negative-v1"):
        if tool in symbol_tools and ":" in key:
            by_tool[tool].add(status)
    for tool, kinds in by_tool.items():
        assert {"SUCCESS", "ERROR", "TIMEOUT"} <= kinds, f"{tool} 负例档不完整: {sorted(kinds)}"
