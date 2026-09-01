"""生成 ctx-session-* 用例的注册 SQL(context-batches 对照通道消费)。

数据来源(全部只读仓库冻结文件,不读运行库):
- 条目 context_items:``bdlh_runtime.session.serializer.serialize_session``
  (引擎自己的 gold-free 序列化器:用户消息 priority 10 / 助手消息 5 /
  工具对合并为不可信条目 3,classification 全部 compressible)——与
  session 通道口径一致,不把 gold 的任何标注放进模型输入;
- 判官方 expected_checks:gold 的 expected_tool_plan / forbidden_claims
  (判官与调度器可见,不进上下文;三个用例 gold 的 required_facts 均为空);
- 变体:仅注册 context-batches 对照通道消费的 3 个变体
  (full / budgeted-hybrid-v1 / budgeted-extractive,预算取 variants.json);
  recent-turns / single-summary 属文件通道基准,不入库。

输出:db/postgresql/changes/20260901-register-ctx-session-cases.sql(幂等)。
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "engine" / "src"))

from bdlh_runtime.session.loader import load_session  # noqa: E402
from bdlh_runtime.session.serializer import serialize_session  # noqa: E402

_CASES_DIR = _REPO / "engine" / "var" / "cases"
_CASES = (
    "ctx-session-database-deploy-01",
    "ctx-session-product-evolution-01",
    "ctx-session-context-engine-debug-01",
)
_CATEGORIES = {
    "ctx-session-database-deploy-01": "长上下文·数据库与部署",
    "ctx-session-product-evolution-01": "长上下文·产品与上下文设计",
    "ctx-session-context-engine-debug-01": "长上下文·上下文引擎排查",
}
#: (variant_id, title, context_strategy, token_budget) —— 与 variants.json 对齐
_COMPARISON_VARIANTS = (
    ("full", "完整上下文(对照)", "full", 65536),
    ("budgeted-hybrid-v1", "按预算压缩(混合主算法)", "budgeted", 8192),
    ("budgeted-extractive", "按预算压缩(抽取式基线)", "budgeted", 8192),
)
_ITEM_TYPE_BY_ROLE = {
    "user_data": "user_message",
    "assistant": "assistant_message",
    "untrusted_data": "tool_observation",
}


def _sql_str(value: str) -> str:
    """普通标量列的 SQL 字面量(单引号转义)。"""

    return "'" + value.replace("'", "''") + "'"


def _sql_json(payload: object) -> str:
    """jsonb 列:dollar 引号包裹的紧凑 JSON 字面量;正文出现定界符即失败(防御)。"""

    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if "$ctx$" in text:
        raise ValueError("payload contains $ctx$ delimiter")
    return "$ctx$" + text + "$ctx$"


def _context_items(case_id: str) -> list[dict]:
    """历史事件(不含当前问题)→ data_fixture.context_items。"""

    case_dir = _CASES_DIR / case_id
    session = load_session(case_dir / f"{case_id}.session.json")
    fingerprint = json.loads((case_dir / "compiled" / "fingerprint.json").read_text(encoding="utf-8"))
    current = next(event for event in session.events if event.event_id == fingerprint["current_event_id"])
    history = dataclasses.replace(session, events=tuple(event for event in session.events if event.seq < current.seq))
    items: list[dict] = []
    for entry in serialize_session(history):
        item = entry.item
        untrusted = not item.trusted
        row = {
            "item_key": item.item_id,
            "item_type": _ITEM_TYPE_BY_ROLE.get(item.role.value, "generic"),
            "classification": item.classification.value,
            "content": item.content,
            "priority": item.priority,
        }
        if untrusted:
            row["untrusted"] = True
        items.append(row)
    return items


def _expected_checks(case_id: str) -> dict:
    gold = json.loads((_CASES_DIR / case_id / "gold" / f"{case_id}.gold.json").read_text(encoding="utf-8"))
    plan = gold["expected_tool_plan"]
    expected_tools: list[str] = []
    for call in plan["required_calls"]:
        name = str(call["tool_name"])
        if name not in expected_tools:
            expected_tools.append(name)
    absent = [str(name) for name in plan["forbidden_calls"]]
    absent += [str(name) for name in plan["nonexistent_tool_names"] if name not in absent]
    return {
        "category": _CATEGORIES[case_id],
        "expected_tools": expected_tools,
        "absent_tools": absent,
        "context_expectations": {
            # gold required_facts 三个用例均为空;forbidden_claims 逐句整串匹配(低误报口径)
            "required_facts": {},
            "forbidden_facts": {f"claim_{index}": claim for index, claim in enumerate(gold["forbidden_claims"], start=1)},
        },
    }


def build_sql() -> str:
    definitions: list[str] = []
    versions: list[str] = []
    variants: list[str] = []
    as_of_rows: list[str] = []

    for case_id in _CASES:
        case_dir = _CASES_DIR / case_id
        raw = json.loads((case_dir / f"{case_id}.session.json").read_text(encoding="utf-8"))
        runtime = raw["runtime_case"]
        definitions.append(f"({_sql_str(case_id)}, {_sql_str(raw['title'])}, 1, 'COMPARISON_CASE')")
        versions.append(
            "({case}, 1, {msg}, {scene}, {auth}, {tools}, 'long-context', {budget}, {checks}, true)".format(
                case=_sql_str(case_id),
                msg=_sql_str(runtime["current_question"]),
                scene=_sql_str(raw["scene"]),
                auth="true" if raw["authenticated"] else "false",
                tools=_sql_json(runtime["visible_tools"]),
                budget=int(runtime["context_target_tokens"]),
                checks=_sql_json(_expected_checks(case_id)),
            )
        )
        fixture = {"fixture_id": f"{case_id}-fixture-v1", "context_items": _context_items(case_id)}
        for variant_id, title, strategy, budget in _COMPARISON_VARIANTS:
            variants.append(
                "({case}, 1, {vid}, {title}, {strategy}, {budget}, {fixture}, true)".format(
                    case=_sql_str(case_id),
                    vid=_sql_str(variant_id),
                    title=_sql_str(title),
                    strategy=_sql_str(strategy),
                    budget=budget,
                    fixture=_sql_json(fixture),
                )
            )
        as_of_rows.append(f"('{case_id}', '{raw['ended_at']}'::timestamptz)")

    return f"""-- ══════════════════════════════════════════════════════════════════════
-- 注册 ctx-session-* 三套 Session 压缩对照用例(context-batches 通道消费)
--
-- 背景:context_eval.COMPARISON_VARIANTS 已迁移为
--   full / budgeted-hybrid-v1 / budgeted-extractive(与 engine/var/cases/
--   ctx-session-*/ctx-session-*.variants.json 对齐),但用例此前未注册入库,
--   POST /api/v1/context-batches 因用例不在目录而 400。
--
-- 内容:
--   1. case_definitions / case_versions:message=current_question、
--      scene/authenticated/visible_tools 取自 session 元数据;
--      expected_checks 来自 gold 判官方(expected_tool_plan/forbidden_claims,
--      判官可见、不进模型输入);
--   2. case_variants × 3(每套相同 context_items,只变 strategy/budget):
--      条目由 bdlh_runtime.session.serializer.serialize_session 生成
--      (用户消息 10 / 助手消息 5 / 工具对不可信 3,全部 compressible),
--      与引擎 session 通道同口径,不读 gold;
--   3. data_snapshots:content=data_fixture,source_hash=其 sha256;
--   4. database_changes 台账登记。
--   仅注册对照通道消费的 3 个变体;recent-turns / single-summary 属文件
--   通道独立基准,不入库。已知限制:通道冻结集为 ab-eval(不含
--   file.read/code.read 等),真实批次的工具判定待通道支持按用例冻结集。
--
-- 执行:psql <连接串> -v ON_ERROR_STOP=1 -f 20260901-register-ctx-session-cases.sql
-- 幂等:全部 INSERT 带 ON CONFLICT DO NOTHING,可安全重跑。
-- 再生成:engine/.venv/Scripts/python engine/scripts/register_ctx_session_cases.py
-- ══════════════════════════════════════════════════════════════════════

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── 1. 用例定义 ────────────────────────────────────────────────────────

INSERT INTO touchstone.case_definitions (id, title, current_version, test_type) VALUES
{",\n".join(definitions)}
ON CONFLICT DO NOTHING;

-- ── 2. 用例版本(expected_checks 为判官方,不进上下文) ────────────────

INSERT INTO touchstone.case_versions
    (case_id, version, message, scene, authenticated, allowed_tools,
     context_profile, token_budget, expected_checks, public)
VALUES
{",\n".join(versions)}
ON CONFLICT DO NOTHING;

-- ── 3. 对照变体(同一份 context_items,唯一变量是 strategy/budget) ────

INSERT INTO touchstone.case_variants
    (case_id, case_version, variant_id, title, context_strategy, token_budget, data_fixture, public)
VALUES
{",\n".join(variants)}
ON CONFLICT DO NOTHING;

-- ── 4. 数据快照(content=变体条目,source_hash=其 sha256) ──────────────

INSERT INTO touchstone.data_snapshots
    (id, case_id, case_version, variant_id, fixture_version, market_as_of, content, source_hash)
SELECT cv.case_id || ':' || cv.variant_id || ':fixture-v1', cv.case_id, cv.case_version,
       cv.variant_id, 'v1', m.as_of, cv.data_fixture,
       'sha256:' || encode(digest(cv.data_fixture::text, 'sha256'), 'hex')
FROM touchstone.case_variants cv
JOIN (VALUES
{",\n".join(as_of_rows)}
) AS m(case_id, as_of) ON m.case_id = cv.case_id
WHERE cv.case_id IN ({", ".join(_sql_str(case_id) for case_id in _CASES)})
ON CONFLICT (id) DO NOTHING;

INSERT INTO touchstone.database_changes (script_name, description)
VALUES ('20260901-register-ctx-session-cases.sql',
        '注册 ctx-session-* 三套 Session 压缩对照用例(每套 full/budgeted-hybrid-v1/budgeted-extractive 三条对照变体及数据快照)')
ON CONFLICT DO NOTHING;

COMMIT;
"""


def main() -> int:
    out = _REPO / "db" / "postgresql" / "changes" / "20260901-register-ctx-session-cases.sql"
    out.write_text(build_sql(), encoding="utf-8", newline="\n")
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
