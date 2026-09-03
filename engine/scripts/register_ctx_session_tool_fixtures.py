"""生成 ctx-session-* 用例冻结工具集注册 SQL(gold runtime_mock_fixtures 入库)。

背景:context-batches 通道原硬编码全局冻结集 ab-eval(无 file.read/code.read),
ctx-session 用例的工具观测全部命中失败桩。接线改造后 runner 按用例
fixture_set_id(variants.json common_conditions)取集;本脚本把各用例 gold 的
runtime_mock_fixtures(按 path 冻结的真实返回,判官方文件、本就供 Mock 使用)
注册为 DB 冻结集,经 data 服务 /tool-fixtures 供通道消费。

call_key 约定:覆盖键「工具名:path」(FrozenObservations 按 symbol→path→基准
依次查找);不注册基准键行——脚本外调用未命中失败桩是冻结纪律,不编造返回。

输出:db/postgresql/changes/20260901-register-ctx-session-tool-fixtures.sql(幂等)。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "engine" / "src"))

from bdlh_runtime.session import load_variants  # noqa: E402

_CASES_DIR = _REPO / "engine" / "var" / "cases"
_CASES = (
    "ctx-session-database-deploy-01",
    "ctx-session-product-evolution-01",
    "ctx-session-context-engine-debug-01",
)


def _sql_str(value: str) -> str:
    """普通标量列的 SQL 字面量(单引号转义)。"""

    return "'" + value.replace("'", "''") + "'"


def _sql_json(payload: object) -> str:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if "$fx$" in text:
        raise ValueError("payload contains $fx$ delimiter")
    return "$fx$" + text + "$fx$"


def _case_bundle(case_id: str) -> tuple[str, list[dict]]:
    case_dir = _CASES_DIR / case_id
    variants = load_variants(case_dir / f"{case_id}.variants.json")
    set_id = str((variants.get("common_conditions") or {}).get("fixture_set_id") or "")
    if not set_id:
        raise ValueError(f"{case_id}: variants.json 未声明 common_conditions.fixture_set_id")
    gold = json.loads((case_dir / "gold" / f"{case_id}.gold.json").read_text(encoding="utf-8"))
    fixtures = gold.get("runtime_mock_fixtures") or []
    if not fixtures:
        raise ValueError(f"{case_id}: gold 无 runtime_mock_fixtures")
    return set_id, fixtures


def build_sql() -> str:
    set_rows: list[str] = []
    response_rows: list[str] = []
    set_ids: list[str] = []

    for case_id in _CASES:
        set_id, fixtures = _case_bundle(case_id)
        set_ids.append(set_id)
        rows_payload = [
            {
                "call_key": f"{item['tool_name']}:{item['match_arguments']['path']}",
                "tool_name": item["tool_name"],
                "arguments": item["match_arguments"],
                "response_status": str(item.get("status") or "success").upper(),
                "response": item["result"],
            }
            for item in fixtures
        ]
        canonical = json.dumps(rows_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        source_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        set_rows.append(
            f"('{set_id}', 1, {_sql_json(case_id + ' 冻结工具返回(按 path,源 gold runtime_mock_fixtures)')}, "
            f"'STATIC', '{source_hash}', false)"
        )
        for sequence, row in enumerate(rows_payload, start=1):
            response_rows.append(
                "('{sid}', 1, {key}, {tool}, {args}, {status}, {resp}, NULL, 0, {seq})".format(
                    sid=set_id,
                    key=_sql_str(row["call_key"]),
                    tool=_sql_str(row["tool_name"]),
                    args=_sql_json(row["arguments"]),
                    status="'{}'".format(row["response_status"]),
                    resp=_sql_json(row["response"]),
                    seq=sequence,
                )
            )

    # f-string 表达式内不能用反斜杠(Python 3.12 才放开,项目基线 3.11),
    # 含 \n 的 join 先落变量再进模板。
    set_rows_sql = ",\n".join(set_rows)
    response_rows_sql = ",\n".join(response_rows)
    change_description = (
        "注册 ctx-session-* 三套用例冻结工具集"
        "(gold runtime_mock_fixtures 按 path 覆盖键入库,供 context-batches 通道按用例取集)"
    )

    return f"""-- ══════════════════════════════════════════════════════════════════════
-- 注册 ctx-session-* 用例冻结工具集(gold runtime_mock_fixtures 入库)
--
-- 背景:context-batches 通道按用例 fixture_set_id 取冻结集(variants.json
-- common_conditions 声明);此前仅有全局 ab-eval(无 file.read/code.read),
-- ctx-session 用例工具观测全部命中失败桩。本脚本把三个用例 gold 的
-- runtime_mock_fixtures(判官方文件,本就供 Mock 使用,按 path 冻结)注册为
-- DB 冻结集,经 data 服务 /tool-fixtures 消费。
--
-- call_key 约定:覆盖键「工具名:path」(engine FrozenObservations 按
-- symbol→path→基准依次查找);不注册基准键行——脚本外调用未命中失败桩
-- 是冻结纪律。response_status 统一大写(与 seed 08 一致)。
-- arguments_hash/response_hash 为 NOT NULL:沿 20260822-fixture-deep-search
-- 的放开→INSERT→回填→恢复模式。
--
-- 执行:psql <连接串> -v ON_ERROR_STOP=1 -f 20260901-register-ctx-session-tool-fixtures.sql
-- 幂等:全部 INSERT 带 ON CONFLICT DO NOTHING,可安全重跑。
-- 再生成:engine/.venv/Scripts/python engine/scripts/register_ctx_session_tool_fixtures.py
-- ══════════════════════════════════════════════════════════════════════

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '15s';
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── 1. 冻结集定义 ──────────────────────────────────────────────────────

INSERT INTO touchstone.fixture_sets
    (id, version, title, fixture_type, source_hash, public)
VALUES
{set_rows_sql}
ON CONFLICT (id, version) DO NOTHING;

-- ── 2. 冻结返回(按 path 覆盖键) ──────────────────────────────────────

ALTER TABLE touchstone.fixture_tool_responses ALTER COLUMN arguments_hash DROP NOT NULL;
ALTER TABLE touchstone.fixture_tool_responses ALTER COLUMN response_hash DROP NOT NULL;

INSERT INTO touchstone.fixture_tool_responses
    (fixture_set_id, fixture_set_version, call_key, tool_name, arguments,
     response_status, response, observed_at, simulated_latency_ms, sequence)
VALUES
{response_rows_sql}
ON CONFLICT (fixture_set_id, fixture_set_version, call_key) DO NOTHING;

UPDATE touchstone.fixture_tool_responses
SET arguments_hash = 'sha256:' || encode(digest(arguments::text, 'sha256'), 'hex'),
    response_hash  = 'sha256:' || encode(digest(response::text, 'sha256'), 'hex')
WHERE fixture_set_id IN ({", ".join("'" + sid + "'" for sid in set_ids)})
  AND arguments_hash IS NULL;

ALTER TABLE touchstone.fixture_tool_responses ALTER COLUMN arguments_hash SET NOT NULL;
ALTER TABLE touchstone.fixture_tool_responses ALTER COLUMN response_hash SET NOT NULL;

INSERT INTO touchstone.database_changes (script_name, description)
VALUES ('20260901-register-ctx-session-tool-fixtures.sql',
        '{change_description}')
ON CONFLICT DO NOTHING;

COMMIT;
"""


def main() -> int:
    out = _REPO / "db" / "postgresql" / "changes" / "20260901-register-ctx-session-tool-fixtures.sql"
    out.write_text(build_sql(), encoding="utf-8", newline="\n")
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
