"""生成对比用例 Mock 修复 SQL(不执行,仅写出脚本文件)。"""

from __future__ import annotations

import json
from pathlib import Path

from bdlh_runtime.experiments.comparison_cases_data import (
    COMPARISON_CASES,
    FIXTURE_SET_ID,
    FIXTURE_SET_VERSION,
    all_mock_fixtures,
    expected_checks_payload,
    fixture_set_source_hash,
)

OUT = (
    Path(__file__).resolve().parents[2] / "db" / "postgresql" / "changes" / "20260826-fix-comparison-mock-and-deps.sql"
)

_STATUS_MAP = {
    "success": "SUCCESS",
    "empty": "SUCCESS",
    "timeout": "TIMEOUT",
    "denied": "DENIED",
    "stale": "SUCCESS",
    "conflict": "ERROR",
    "error": "ERROR",
}


def sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main() -> None:
    source_hash = fixture_set_source_hash()
    fixtures = all_mock_fixtures()
    lines: list[str] = []
    lines.append("-- 对比用例 Mock 匹配、调用依赖与 fixture 哈希修复")
    lines.append("-- 手工执行;应用与测试不得自动扫描执行。")
    lines.append("-- 依赖: 已执行 20260825-two-track-experiments.sql(或至少已有 cmp-* 用例)。")
    lines.append("-- 不停止服务亦可执行;建议先备份 case_versions / fixture_sets。")
    lines.append("--")
    lines.append("-- 过渡说明: Data 服务当前仍从 expected_checks.mock_fixtures 读取详细状态")
    lines.append("-- (empty/conflict/stale 等)。fixture_tool_responses 同步落库作为可验证单一")
    lines.append("-- 来源副本;response_status 受表约束映射到 SUCCESS/TIMEOUT/ERROR/DENIED,")
    lines.append("-- 细粒度 status 保留在 response.eval_status 与 expected_checks 中。")
    lines.append("BEGIN;")
    lines.append("SET LOCAL lock_timeout = '5s';")
    lines.append("SET LOCAL statement_timeout = '10min';")
    lines.append("")
    lines.append(
        "INSERT INTO touchstone.fixture_sets (id, version, title, fixture_type, source_hash, captured_at, public)"
    )
    lines.append("VALUES (")
    lines.append(f"  {sql_quote(FIXTURE_SET_ID)}, {FIXTURE_SET_VERSION},")
    lines.append("  '对比用例冻结 Mock 集(20条,显式匹配与依赖)',")
    lines.append(f"  'STATIC', {sql_quote(source_hash)}, now(), true")
    lines.append(")")
    lines.append("ON CONFLICT (id, version) DO UPDATE SET")
    lines.append("  title = EXCLUDED.title,")
    lines.append("  source_hash = EXCLUDED.source_hash,")
    lines.append("  captured_at = EXCLUDED.captured_at;")
    lines.append("")
    lines.append("DELETE FROM touchstone.fixture_tool_responses")
    lines.append(f"WHERE fixture_set_id = {sql_quote(FIXTURE_SET_ID)} AND fixture_set_version = {FIXTURE_SET_VERSION};")
    lines.append("")
    lines.append("ALTER TABLE touchstone.fixture_tool_responses ALTER COLUMN arguments_hash DROP NOT NULL;")
    lines.append("ALTER TABLE touchstone.fixture_tool_responses ALTER COLUMN response_hash DROP NOT NULL;")
    lines.append("")

    for index, fx in enumerate(fixtures):
        call_key = str(fx["fixture_id"])
        match = fx.get("match_arguments") or {}
        result = dict(fx.get("result") or {})
        result["eval_status"] = fx.get("status")
        result["match_mode"] = fx.get("match_mode") or "subset"
        result["simulated"] = True
        args_json = json.dumps(match, ensure_ascii=False, separators=(",", ":"))
        resp_json = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        db_status = _STATUS_MAP.get(str(fx.get("status") or "success"), "ERROR")
        lines.append(
            "INSERT INTO touchstone.fixture_tool_responses "
            "(fixture_set_id, fixture_set_version, call_key, tool_name, arguments,"
            " response_status, response, simulated_latency_ms, sequence)"
        )
        lines.append("VALUES (")
        lines.append(f"  {sql_quote(FIXTURE_SET_ID)}, {FIXTURE_SET_VERSION}, {sql_quote(call_key)},")
        lines.append(f"  {sql_quote(str(fx['tool']))}, {sql_quote(args_json)}::jsonb,")
        lines.append(f"  {sql_quote(db_status)}, {sql_quote(resp_json)}::jsonb, 0, {index}")
        lines.append(");")
        lines.append("")

    lines.append("UPDATE touchstone.fixture_tool_responses")
    lines.append("SET arguments_hash = 'sha256:' || encode(digest(arguments::text, 'sha256'), 'hex'),")
    lines.append("    response_hash  = 'sha256:' || encode(digest(response::text, 'sha256'), 'hex')")
    lines.append(f"WHERE fixture_set_id = {sql_quote(FIXTURE_SET_ID)} AND fixture_set_version = {FIXTURE_SET_VERSION};")
    lines.append("ALTER TABLE touchstone.fixture_tool_responses ALTER COLUMN arguments_hash SET NOT NULL;")
    lines.append("ALTER TABLE touchstone.fixture_tool_responses ALTER COLUMN response_hash SET NOT NULL;")
    lines.append("")

    for case in COMPARISON_CASES:
        checks = expected_checks_payload(case)
        checks_json = json.dumps(checks, ensure_ascii=False, separators=(",", ":"))
        allowed = json.dumps(case["allowed_tools"], ensure_ascii=False, separators=(",", ":"))
        lines.append(f"-- {case['case_id']}")
        lines.append("UPDATE touchstone.case_versions SET")
        lines.append(f"  message = {sql_quote(case['message'])},")
        lines.append(f"  scene = {sql_quote(case['scene'])},")
        lines.append(f"  authenticated = {'true' if case['authenticated'] else 'false'},")
        lines.append(f"  allowed_tools = {sql_quote(allowed)}::jsonb,")
        lines.append(f"  expected_checks = {sql_quote(checks_json)}::jsonb")
        lines.append(f"WHERE case_id = {sql_quote(case['case_id'])} AND version = 1;")
        lines.append("")
        lines.append("UPDATE touchstone.case_definitions SET")
        lines.append(f"  title = {sql_quote(case['title'])}")
        lines.append(f"WHERE id = {sql_quote(case['case_id'])};")
        lines.append("")

    lines.append("UPDATE touchstone.data_snapshots SET")
    lines.append(f"  fixture_set_id = {sql_quote(FIXTURE_SET_ID)},")
    lines.append(f"  fixture_set_version = {FIXTURE_SET_VERSION},")
    lines.append(
        "  content = jsonb_build_object('note', " + sql_quote(f"对比用例标准条件;冻结 Mock 集 {FIXTURE_SET_ID}") + "),"
    )
    lines.append(f"  source_hash = {sql_quote(source_hash)}")
    lines.append("WHERE case_id LIKE 'cmp-%';")
    lines.append("")
    lines.append("INSERT INTO touchstone.database_changes (script_name, description)")
    lines.append(
        "VALUES ('20260826-fix-comparison-mock-and-deps.sql',"
        " '校正20条对比用例 Mock 匹配、依赖结构与 fixture 内容哈希');"
    )
    lines.append("COMMIT;")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"source_hash={source_hash} fixtures={len(fixtures)}")


if __name__ == "__main__":
    main()
