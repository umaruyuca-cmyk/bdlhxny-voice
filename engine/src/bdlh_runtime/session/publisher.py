"""Session 交叉验证的脱敏静态发布器(--publish)。

把冻结工件发布为 web 纯静态站可读的 JSON(覆盖式快照),目录结构:
``web/public/showcase-data/session-cross/``

- ``index.json``:用例元信息(变体列表与各自 token 预算/hash、12 格矩阵、发布时间);
- ``session.json``:按序事件时间线(user_message / assistant_message / tool_call /
  tool_result 的正文与状态),不含任何评测标注;
- ``compiled/{variant_id}.json``:冻结派生工件副本(消息、token、hash、事件桶、
  warnings;v2 启用时含 scores 因子明细——是可解释性证据,不是答案);
- ``report.json`` + ``report.md``:最新一次实验的聚合与逐格下钻;未跑实验时
  ``report.json`` 为 ``{"status": "not_run"}`` 占位。

隔离红线:发布器不 import gold 相关模块、不读取 gold 文件;发布后按 gold 特征
字段名(current_active_constraints / superseded_decisions / expected_tool_plan /
answer_rubric)对产物做零命中自检,命中即抛错回滚该次发布。
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from .loader import load_session, load_variants

#: gold 特征字段名(仅字段名,用于零命中自检;不读取 gold 内容)
_GOLD_MARKER_FIELDS = (
    "current_active_constraints",
    "superseded_decisions",
    "expected_tool_plan",
    "answer_rubric",
)


def publish_session_cross(
    case_dir: Path,
    compile_report: dict[str, Any],
    web_dir: Path,
    *,
    report: dict[str, Any] | None = None,
    markdown: str | None = None,
) -> Path:
    """发布静态工件(覆盖式快照);返回发布目录。"""

    case_name = case_dir.name
    session = load_session(case_dir / f"{case_name}.session.json")
    variants = load_variants(case_dir / f"{case_name}.variants.json")

    target = Path(web_dir)
    target.mkdir(parents=True, exist_ok=True)

    # 1) 原始 Session 时间线(白名单字段,无评测标注)
    timeline = [
        {
            key: event.__dict__[key]
            for key in (
                "seq",
                "event_id",
                "occurred_at",
                "type",
                "content",
                "role",
                "tool_name",
                "call_id",
                "status",
                "error_code",
            )
            if event.__dict__.get(key) is not None
        }
        for event in session.events
    ]
    (target / "session.json").write_text(
        json.dumps(
            {
                "case_id": session.session_id,
                "case_version": session.session_version,
                "title": session.title,
                "event_count": len(session.events),
                "current_question": session.current_question,
                "visible_tools": list(session.visible_tools),
                "events": timeline,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # 2) 冻结派生工件副本(来自 compiled/*.json,本就无 gold)
    compiled_dir = target / "compiled"
    if compiled_dir.exists():
        shutil.rmtree(compiled_dir)
    compiled_dir.mkdir(parents=True, exist_ok=True)
    variant_rows: list[dict[str, Any]] = []
    compiled_payloads: dict[str, Any] = compile_report.get("compiled") or {}
    for variant in variants.get("context_variants") or []:
        variant_id = str(variant["variant_id"])
        payload = compiled_payloads.get(variant_id) or {}
        source = case_dir / "compiled" / f"{variant_id}.json"
        if source.is_file():
            shutil.copyfile(source, compiled_dir / f"{variant_id}.json")
        elif payload:
            (compiled_dir / f"{variant_id}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        variant_rows.append(
            {
                "variant_id": variant_id,
                "title": variant.get("title") or variant_id,
                "strategy": variant.get("strategy"),
                "strategy_version": payload.get("strategy_version") or variant.get("strategy_version"),
                "token_budget": payload.get("token_budget") or variant.get("token_budget"),
                "compiled_context_hash": payload.get("compiled_context_hash"),
                "original_tokens": payload.get("original_tokens"),
                "working_tokens": payload.get("working_tokens"),
                "build_duration_ms": payload.get("build_duration_ms"),
                "build_model_calls": payload.get("build_model_calls", 0),
                "build_input_tokens": payload.get("build_input_tokens", 0),
                "build_output_tokens": payload.get("build_output_tokens", 0),
                "build_cost": payload.get("build_cost", 0.0),
                "has_scores": bool(payload.get("scores")),
                "uses_summary_model": bool(variant.get("uses_summary_model")),
                "uses_custom_budgeted_algorithm": bool(variant.get("uses_custom_budgeted_algorithm")),
                "notes": variant.get("notes") or "",
            }
        )

    # 3) index.json:用例元信息 + 矩阵
    (target / "index.json").write_text(
        json.dumps(
            {
                "case_id": session.session_id,
                "case_version": session.session_version,
                "event_count": len(session.events),
                "source_session_hash": session.source_hash,
                "tokenizer_version": compile_report.get("tokenizer_version"),
                "agent_modes": list(variants.get("agent_modes") or []),
                "variants": variant_rows,
                "matrix": list(variants.get("matrix") or []),
                "published_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "notice": "所有工具返回均为冻结 Mock(simulated),不代表真实第三方 API 质量",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # 4) report.json / report.md:最新一次实验(或 not_run 占位)
    if report is None:
        report_payload: dict[str, Any] = {"status": "not_run"}
    else:
        report_payload = {
            "status": "run",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "experiment_type": report.get("experiment_type"),
            "evaluator_version": report.get("evaluator_version"),
            "case_id": report.get("case_id"),
            "case_version": report.get("case_version"),
            "model": report.get("model"),
            "git_commit": report.get("git_commit"),
            "runs_per_cell": report.get("runs_per_cell"),
            "frozen_conditions": report.get("frozen_conditions"),
            "by_variant": report.get("by_variant"),
            "by_mode": report.get("by_mode"),
            "cells": report.get("cells"),
            "notice": "所有工具返回均为冻结 Mock(simulated),不代表真实第三方 API 质量",
        }
    (target / "report.json").write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (target / "report.md").write_text(markdown or "# Session 交叉验证(尚未运行实验)\n", encoding="utf-8")

    # 5) data.js:页面嵌入数据(file:// 直开时 fetch 不可用,经 <script> 加载)
    bundle = {
        "index": json.loads((target / "index.json").read_text(encoding="utf-8")),
        "session": json.loads((target / "session.json").read_text(encoding="utf-8")),
        "compiled": {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(compiled_dir.glob("*.json"))
        },
        "report": report_payload,
    }
    (target / "data.js").write_text(
        "window.SESSION_CROSS_DATA = "
        + json.dumps(bundle, ensure_ascii=False, default=str).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
        + ";\n",
        encoding="utf-8",
    )

    _assert_no_gold_leakage(target)
    return target


def _assert_no_gold_leakage(published_dir: Path) -> None:
    """发布产物对 gold 特征字段零命中自检;命中即删除产物并抛错。"""

    offenders: list[str] = []
    for path in sorted(published_dir.rglob("*.json")):
        text = path.read_text(encoding="utf-8")
        for marker in _GOLD_MARKER_FIELDS:
            if marker in text:
                offenders.append(f"{path.name}:{marker}")
    if offenders:
        shutil.rmtree(published_dir)
        raise RuntimeError(f"发布产物命中 gold 特征字段,已回滚:{', '.join(offenders)}")
