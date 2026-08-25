"""Session 交叉验证 runner:4 上下文策略 × 3 Agent 模式 = 12 组矩阵。

两种模式:
- ``--compile-only``(默认):只编译四份派生输入并冻结成工件,**不读取 gold、
  不调用模型**——可在无密钥环境验证数据结构、编译流程与预算口径;
- 完整模式(需 LLM_API_KEY):读取 gold 配置冻结 Mock,按矩阵逐格运行三种
  Agent 实现,重复有效次数由 ``--runs`` 指定,产出 JSON + Markdown 报告。

冻结纪律:
- 四份派生输入先编译、hash、落盘,三个 Agent 模式读取同一份冻结工件
  (treatment 组通过 FrozenContextBuilder 按 item id 命中冻结结果);
- gold 只被 Mock 调度器与评测器读取,编译链路结构上不可见。

CLI: python -m bdlh_runtime.evaluation.session_cross_eval [--compile-only] [--runs 3]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from bdlh_runtime.context import (
    ConservativeTokenCounter,
    ContextBuildRequest,
    ContextBuildResult,
    ContextBuilder,
)
from bdlh_runtime.engine.loop import AgentLoop, AgentTurn, _tool_schema_tokens, load_prompt
from bdlh_runtime.evaluation.ab_eval import build_llm_from_env
from bdlh_runtime.evaluation.baseline_agent import naive_run
from bdlh_runtime.evaluation.baseline_langgraph import react_official_run
from bdlh_runtime.evaluation.run_telemetry import classify_failure, validity_of
from bdlh_runtime.session import (
    SessionCompiler,
    SessionMockDispatcher,
    dispatcher_from_gold,
    judge_session_run,
    load_gold,
    load_session,
    load_variants,
    serialize_session,
)
from bdlh_runtime.tools.catalog import ToolCard, ToolCatalog

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CASE_DIR = _REPO_ROOT / "engine" / "var" / "cases" / "ctx-session-touchstone-design-01"
EVALUATOR_VERSION = "session-cross-eval-v1"

AGENT_MODES = ("baseline-tool-calling", "langgraph-react", "full-system")

#: 会话用例的通用只读工具目录(required_scope 为空 → 全场景可见)
_SESSION_TOOL_DESCRIPTIONS: dict[str, str] = {
    "file.read": "读取指定路径的文件内容。参数 path 为绝对或仓库相对路径。",
    "file.search": "在文件内容中搜索关键词,返回命中位置。",
    "document.summarize": "对给定文档文本生成摘要。",
    "code.read": "读取指定源码文件的完整内容。参数 path 为文件路径。",
    "code.search": "在代码库中检索符号或关键字,返回命中文件与行号。",
    "git.get_diff": "查看 Git 工作区或提交差异(只读)。",
    "project.get_status": "查看项目当前状态:分支、工作区、环境(只读)。",
}


def session_tool_catalog(visible_tools: list[str] | tuple[str, ...]) -> ToolCatalog:
    catalog = ToolCatalog()
    for name in sorted(visible_tools):
        catalog.register(
            ToolCard(
                name=name,
                description=_SESSION_TOOL_DESCRIPTIONS.get(name, f"通用只读工具:{name}"),
                parameters={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True,
                },
                read_only=True,
                required_scope=[],
            )
        )
    return catalog


class FrozenContextBuilder:
    """首轮构建命中冻结工件(item id 全等);循环内 refit 条目变化走真实构建器。"""

    def __init__(self, real: ContextBuilder, frozen_ids: tuple[str, ...], frozen: ContextBuildResult) -> None:
        self._real = real
        self._frozen_ids = frozen_ids
        self._frozen = frozen

    def build(self, request: ContextBuildRequest) -> ContextBuildResult:
        if tuple(item.item_id for item in request.items) == self._frozen_ids:
            return self._frozen
        return self._real.build(request)


class RecordingSessionExecutor:
    """包装 Mock 调度器,维护 (name, arguments) 调用日志(react 组需要 .call_log)。"""

    def __init__(self, dispatcher: SessionMockDispatcher) -> None:
        self._dispatcher = dispatcher
        self.call_log: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._dispatcher(name, arguments)
        self.call_log.append((name, dict(arguments)))
        return result

    @property
    def records(self) -> list[dict[str, Any]]:
        return [record.to_payload() for record in self._dispatcher.call_log]


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=_REPO_ROOT
        ).stdout.strip()
    except Exception:  # noqa: BLE001 —— 无 git 环境时记录 unknown
        return "unknown"


def compile_all(
    case_dir: Path,
    *,
    write: bool = True,
    llm_summary: bool = False,
) -> dict[str, Any]:
    """编译四份派生输入并冻结;此函数绝不读取 gold。"""

    session = load_session(case_dir / f"{case_dir.name}.session.json")
    variants = load_variants(case_dir / f"{case_dir.name}.variants.json")
    compiler = SessionCompiler.from_env(llm_summary=llm_summary)
    common_rules = load_prompt("system_base.md", "scene_chat.md")

    compiled: dict[str, Any] = {}
    for variant in variants.get("context_variants") or []:
        variant_id = str(variant["variant_id"])
        started = time.perf_counter()
        try:
            artifact = compiler.compile(session, variant, common_rules=common_rules)
            payload = artifact.to_payload()
            payload["status"] = "COMPLETE"
        except ValueError as exc:  # full-session 超窗等 → 按变体配置记为无效上下文
            payload = {
                "case_id": session.session_id,
                "case_version": session.session_version,
                "source_session_hash": session.source_hash,
                "variant_id": variant_id,
                "strategy_version": str(variant.get("strategy_version") or ""),
                "token_budget": int(variant.get("token_budget") or 0),
                "status": "INVALID",
                "error": str(exc),
                "overflow_behavior": str(variant.get("overflow_behavior") or ""),
            }
        payload["compile_wall_ms"] = round((time.perf_counter() - started) * 1000)
        compiled[variant_id] = payload
        if write:
            out = case_dir / "compiled" / f"{variant_id}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    checks = _compile_checks(session, variants, compiled)
    return {
        "case_id": session.session_id,
        "case_version": session.session_version,
        "source_session_hash": session.source_hash,
        "event_count": len(session.events),
        "tokenizer_version": compiler.tokenizer_version,
        "compiled": compiled,
        "checks": checks,
        "checks_pass": all(row["passed"] for row in checks),
    }


def _compile_checks(session: Any, variants: dict[str, Any], compiled: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    hashes = {row.get("source_session_hash") for row in compiled.values()}
    checks.append(
        {
            "check": "same_source_session_hash",
            "passed": len(hashes) == 1 and session.source_hash in hashes,
            "detail": sorted(str(item) for item in hashes),
        }
    )
    variant_ids = {str(row.get("variant_id")) for row in variants.get("context_variants") or []}
    checks.append(
        {
            "check": "four_unique_variants_compiled",
            "passed": set(compiled) == variant_ids and len(compiled) == 4,
            "detail": sorted(compiled),
        }
    )
    matrix = variants.get("matrix") or []
    expected_cells = {(str(row.get("context_variant")), str(row.get("agent_mode"))) for row in matrix}
    checks.append(
        {
            "check": "matrix_has_12_cells",
            "passed": len(expected_cells) == 12 and len(matrix) == 12,
            "detail": f"{len(matrix)} cells",
        }
    )
    completed = [row for row in compiled.values() if row.get("status") == "COMPLETE"]
    budget_ok = all(row.get("budget_fit") for row in completed)
    checks.append({"check": "completed_variants_fit_budget", "passed": budget_ok, "detail": f"{len(completed)}/4 complete"})
    required_ok = all(row.get("required_retained") for row in completed)
    checks.append({"check": "required_retained_in_completed", "passed": required_ok, "detail": ""})
    checks.append(
        {
            "check": "compiler_never_reads_gold",
            "passed": True,
            "detail": "structural: SessionCompiler.compile() 签名不含 gold,接口层阻断答案泄漏",
        }
    )
    return checks


async def run_matrix(
    case_dir: Path,
    *,
    model: str,
    runs: int,
    llm: Any,
    write: bool = True,
    llm_summary: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """运行 12 格矩阵;返回 (report, compiled_by_variant)(后者供落库/发布用)。"""

    session = load_session(case_dir / f"{case_dir.name}.session.json")
    variants = load_variants(case_dir / f"{case_dir.name}.variants.json")
    gold = load_gold(case_dir / "gold" / f"{case_dir.name}.gold.json")
    common_rules = load_prompt("system_base.md", "scene_chat.md")

    catalog = session_tool_catalog(session.visible_tools)
    cards = catalog.list()
    schema_tokens = _tool_schema_tokens(cards, ConservativeTokenCounter())
    compiler = SessionCompiler.from_env(llm_summary=llm_summary)
    compiled_by_variant: dict[str, Any] = {}
    for variant in variants.get("context_variants") or []:
        compiled_by_variant[str(variant["variant_id"])] = compiler.compile(session, variant, common_rules=common_rules)

    cells = []
    for cell in variants.get("matrix") or []:
        variant_id = str(cell["context_variant"])
        mode = str(cell["agent_mode"])
        artifact = compiled_by_variant.get(variant_id)
        cell_runs = []
        if artifact is None:
            cells.append(
                {
                    "context_variant": variant_id,
                    "agent_mode": mode,
                    "runs": [],
                    "error": "variant compile missing",
                }
            )
            continue
        for repeat in range(runs):
            run_key = f"{session.session_id}:{variant_id}:{mode}:{repeat}"
            dispatcher = dispatcher_from_gold(gold)
            executor = RecordingSessionExecutor(dispatcher)
            started = time.perf_counter()
            try:
                if mode == "full-system":
                    serialized = serialize_session(session)
                    turn = AgentTurn(
                        user_id=session.owner_id or "session-owner",
                        message=session.current_question,
                        scene_tag="general",
                        authenticated=True,
                        run_id=run_key,
                        context_entries=tuple(entry.item for entry in serialized),
                        context_strategy=artifact.strategy,
                        token_budget=artifact.token_budget + schema_tokens,
                        owner_id=None,
                    )
                    frozen_ids = ("system-prompt",) + tuple(
                        item.item_id for item in turn.context_entries
                    ) + ("current-question",)
                    frozen_builder = FrozenContextBuilder(
                        ContextBuilder(), frozen_ids, artifact.build_result
                    )
                    loop = AgentLoop(
                        llm=llm,
                        catalog=catalog,
                        executor=executor,
                        tool_loading="scoped",
                        max_tool_calls=20,
                        context_builder=frozen_builder,
                    )
                    agent_result = await asyncio.wait_for(
                        loop.run(turn), timeout=float(os.getenv("EVAL_RUN_TIMEOUT_S", "300"))
                    )
                    answer = agent_result.answer
                    error = agent_result.context_error if agent_result.degraded else None
                    tool_calls = list(executor.call_log)
                else:
                    system_content = "\n\n".join(
                        m.content for m in artifact.compiled_messages if m.role == "system"
                    ) or "你是软件架构评审助手,只使用提供的工具,不编造结果。"
                    context_parts = [m.content for m in artifact.compiled_messages if m.role != "system"]
                    fed_message = "\n\n".join(context_parts) or session.current_question
                    if mode == "baseline-tool-calling":
                        result = await asyncio.wait_for(
                            naive_run(
                                message=fed_message,
                                history=[],
                                all_cards=cards,
                                llm=llm,
                                executor=executor,
                                system_prompt=system_content,
                            ),
                            timeout=float(os.getenv("EVAL_RUN_TIMEOUT_S", "300")),
                        )
                    else:
                        result = await asyncio.wait_for(
                            react_official_run(
                                message=fed_message,
                                history=[],
                                all_cards=cards,
                                llm=llm,
                                executor=executor,
                                system_prompt=system_content,
                            ),
                            timeout=float(os.getenv("EVAL_RUN_TIMEOUT_S", "300")),
                        )
                    answer = result.answer
                    error = result.error
                    tool_calls = list(result.tool_calls)
                    for attempted in getattr(result, "attempted_tools", []) or []:
                        executed = {name for name, _ in tool_calls}
                        if attempted not in executed:
                            tool_calls.append((attempted, {}))
            except TimeoutError:
                answer, error, tool_calls = "", "运行超时(timed out):单运行熔断", list(executor.call_log)
            except Exception as exc:  # noqa: BLE001 —— 异常降级为一次运行
                answer, error, tool_calls = "", str(exc), list(executor.call_log)

            status, category = classify_failure(error)
            judgment = judge_session_run(
                compiled=artifact,
                gold=gold,
                tool_calls=tool_calls,
                answer=answer,
                visible_tools=session.visible_tools,
                validity=validity_of(status),
                error_category=category,
            )
            cell_runs.append(
                {
                    "run_key": run_key,
                    "repeat_index": repeat,
                    "answer": answer,
                    "error": error,
                    "validity": judgment.validity,
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                    "tool_calls": [
                        {"tool": name, "arguments": args} for name, args in tool_calls
                    ],
                    "mock_records": executor.records,
                    "judgment": asdict(judgment),
                }
            )
            await asyncio.sleep(float(os.getenv("EVAL_INTER_RUN_DELAY_S", "1")))
        cells.append({"context_variant": variant_id, "agent_mode": mode, "runs": cell_runs})

    report = {
        "experiment_type": "session-cross",
        "evaluator_version": EVALUATOR_VERSION,
        "case_id": session.session_id,
        "case_version": session.session_version,
        "model": model,
        "git_commit": _git_commit(),
        "generated_date": time.strftime("%Y%m%d"),
        "runs_per_cell": runs,
        "tool_schema_tokens_estimated": schema_tokens,
        "frozen_conditions": {
            **(variants.get("common_conditions") or {}),
            "tool_schema_tokens": schema_tokens,
            "common_prompt_hash": hashlib.sha256(common_rules.encode("utf-8")).hexdigest()[:16],
            "tokenizer_version": compiler.tokenizer_version,
            "budgeted_scoring": (os.getenv("BUDGETED_SCORING") or "").strip() or "v1",
            "budgeted_scoring_scene": (os.getenv("BUDGETED_SCORING_SCENE") or "").strip() or "default",
            "llm_summary": llm_summary,
            "source_session_hash": session.source_hash,
            "compiled_context_hashes": {
                variant_id: artifact.compiled_context_hash
                for variant_id, artifact in compiled_by_variant.items()
            },
        },
        "cells": cells,
        "by_variant": _aggregate(cells, key="context_variant"),
        "by_mode": _aggregate(cells, key="agent_mode"),
    }
    if write:
        out = case_dir / f"cross-report-{time.strftime('%Y%m%d')}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return report, compiled_by_variant


def _aggregate(cells: list[dict[str, Any]], *, key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for cell in cells:
        for run in cell.get("runs") or []:
            grouped.setdefault(f"{cell[key]}", []).append(run)
    summary: dict[str, dict[str, Any]] = {}
    for group, runs in sorted(grouped.items()):
        valid = [run for run in runs if run["validity"] == "VALID"]
        judgments = [run["judgment"] for run in valid]
        # asdict() 不序列化 @property(selection_rate),从字段现算
        selection_rates = [
            (plan["required_hit"] / plan["required_total"]) if plan["required_total"] else 1.0
            for plan in (j["tool_plan"] for j in judgments)
        ] or [0.0]
        retentions = [j["constraint_retention"] for j in judgments] or [0.0]
        summary[group] = {
            "total_runs": len(runs),
            "valid_runs": len(valid),
            "invalid_runs": len(runs) - len(valid),
            "mean_tool_selection_rate": round(statistics.mean(selection_rates), 4),
            "mean_constraint_retention": round(statistics.mean(retentions), 4),
            "superseded_misuse_runs": sum(1 for j in judgments if j["superseded_misuse"]),
            "forbidden_claim_runs": sum(1 for j in judgments if j["forbidden_claims_in_answer"]),
            "no_file_change_statement_runs": sum(1 for j in judgments if j["states_no_file_changes"]),
            "mean_duration_ms": round(statistics.mean([r["duration_ms"] for r in valid])) if valid else 0,
        }
    return summary


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Session 交叉验证报告(4 上下文策略 × 3 Agent 模式)",
        "",
        f"- 用例:{report['case_id']} v{report['case_version']}",
        f"- 模型:{report['model']}; 每格有效重复:{report['runs_per_cell']}",
        f"- 评测器:{report['evaluator_version']}; Git:{report['git_commit'][:12]}",
        f"- 工具 Schema 估算:{report.get('tool_schema_tokens_estimated')} token(全格一致)",
        "",
        "## 固定上下文 → 比较 Agent 模式(by_variant)",
        "",
        "| 上下文策略 | 有效运行 | 工具选择率 | 约束保留率 | 废弃误用 | 禁用说法 | 声明未改文件 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for group, row in report.get("by_variant", {}).items():
        lines.append(
            f"| {group} | {row['valid_runs']}/{row['total_runs']} "
            f"| {row['mean_tool_selection_rate']:.0%} | {row['mean_constraint_retention']:.0%} "
            f"| {row['superseded_misuse_runs']} | {row['forbidden_claim_runs']} "
            f"| {row['no_file_change_statement_runs']} |"
        )
    lines += [
        "",
        "## 固定 Agent 模式 → 比较上下文策略(by_mode)",
        "",
        "| Agent 模式 | 有效运行 | 工具选择率 | 约束保留率 | 废弃误用 | 禁用说法 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for group, row in report.get("by_mode", {}).items():
        lines.append(
            f"| {group} | {row['valid_runs']}/{row['total_runs']} "
            f"| {row['mean_tool_selection_rate']:.0%} | {row['mean_constraint_retention']:.0%} "
            f"| {row['superseded_misuse_runs']} | {row['forbidden_claim_runs']} |"
        )
    lines += [
        "",
        "## 口径",
        "",
        "- INVALID 运行不进入能力指标分母;单格失败保留下钻(run_key → tool_calls/mock_records)",
        "- 所有工具返回均为冻结 Mock,结论只覆盖 Agent 决策与上下文处理,不代表真实 API 质量",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from bdlh_runtime.infra.env import load_deploy_env

    load_deploy_env()  # LLM/data 配置统一来自 deploy/.env(已存在的环境变量优先)

    parser = argparse.ArgumentParser(description="Session 交叉验证(4×3)")
    parser.add_argument("--case-dir", type=str, default=str(DEFAULT_CASE_DIR))
    parser.add_argument("--compile-only", action="store_true", help="只编译冻结工件(不读 gold、不调模型)")
    parser.add_argument("--runs", type=int, default=3, help="每格重复次数")
    parser.add_argument("--model", type=str, default=os.getenv("LLM_MODEL", "Qwen/Qwen3.6-35B-A3B"))
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument(
        "--llm-summary",
        action="store_true",
        default=bool((os.getenv("LLM_SUMMARY") or "").strip() in {"1", "true", "yes"}),
        help="single-summary 变体接真实 LLM 一次性摘要(LLM_SUMMARY=1 等效;失败自动回退抽取式)",
    )
    parser.add_argument(
        "--dry-db",
        action="store_true",
        help="构造全部落库载荷并打印(脱敏),不发送任何请求,供无 data 服务环境验证",
    )
    parser.add_argument(
        "--save-db",
        action="store_true",
        help="经 data 服务落库(需本地 data 服务 + DATA_API_BASE_URL 指向本地;批次不可变,重复运行生成新批次)",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="把脱敏静态工件发布到 web/public/showcase-data/session-cross/(gold 永不发布)",
    )
    args = parser.parse_args(argv)

    case_dir = Path(args.case_dir)
    compile_report = compile_all(case_dir, write=not args.no_write, llm_summary=args.llm_summary)
    print(
        json.dumps(
            {
                k: compile_report[k]
                for k in ("case_id", "source_session_hash", "event_count", "tokenizer_version")
            },
            ensure_ascii=False,
        )
    )
    for row in compile_report["checks"]:
        print(f"  [{'PASS' if row['passed'] else 'FAIL'}] {row['check']} {row['detail']}")
    if not compile_report["checks_pass"]:
        print("编译校验未通过,停止。")
        return 1

    if args.compile_only:
        if not args.no_write:
            out = case_dir / "compiled" / "compile-report.json"
            out.write_text(json.dumps(compile_report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"compile report written to {out}")
        if args.dry_db:
            _print_dry_db_from_compile(compile_report, args.model)
        if args.publish:
            _publish_static(case_dir, compile_report)
        return 0

    if not os.getenv("LLM_API_KEY"):
        print("完整模式需要 LLM_API_KEY;当前环境未配置。可先用 --compile-only 验证编译链路。")
        return 1
    llm = build_llm_from_env(args.model)
    report, compiled_by_variant = asyncio.run(
        run_matrix(
            case_dir,
            model=args.model,
            runs=args.runs,
            llm=llm,
            write=not args.no_write,
            llm_summary=args.llm_summary,
        )
    )
    markdown = render_markdown(report)
    if not args.no_write:
        out = case_dir / "cross-report.md"
        out.write_text(markdown, encoding="utf-8")
        print(f"report written to {out}")
    print(markdown)
    if args.dry_db:
        _print_dry_db(report, compiled_by_variant, case_dir, compile_report["tokenizer_version"])
    if args.save_db:
        if _save_to_db(report, compiled_by_variant, case_dir, compile_report["tokenizer_version"]) != 0:
            return 1
    if args.publish:
        _publish_static(case_dir, compile_report, report=report, markdown=markdown)
    return 0


def _publish_static(
    case_dir: Path,
    compile_report: dict[str, Any],
    *,
    report: dict[str, Any] | None = None,
    markdown: str | None = None,
) -> None:
    """--publish:把脱敏静态工件写到 web/public/showcase-data/session-cross/。"""

    from bdlh_runtime.session.publisher import publish_session_cross

    web_dir = _REPO_ROOT / "web" / "public" / "showcase-data" / "session-cross"
    try:
        target = publish_session_cross(case_dir, compile_report, web_dir, report=report, markdown=markdown)
    except RuntimeError as exc:
        print(f"[--publish] 发布失败:{exc}")
        return
    print(f"[--publish] 静态工件已发布到 {target}(gold 零命中自检通过)")


def _print_dry_db_from_compile(compile_report: dict[str, Any], model: str) -> None:
    """--compile-only --dry-db:打印批次载荷骨架(完整模式的运行载荷需真实运行)。"""

    from bdlh_runtime.evaluation.session_cross_db import build_batch_payload, sanitize_for_print

    pseudo = {
        "case_id": compile_report.get("case_id"),
        "case_version": compile_report.get("case_version"),
        "model": model,
        "evaluator_version": EVALUATOR_VERSION,
        "git_commit": _git_commit(),
        "generated_date": time.strftime("%Y%m%d"),
        "frozen_conditions": {
            "source_session_hash": compile_report.get("source_session_hash"),
            "compiled_context_hashes": {
                variant_id: payload.get("compiled_context_hash")
                for variant_id, payload in (compile_report.get("compiled") or {}).items()
            },
            "tokenizer_version": compile_report.get("tokenizer_version"),
            "budgeted_scoring": (os.getenv("BUDGETED_SCORING") or "").strip() or "v1",
            "llm_summary": bool((os.getenv("LLM_SUMMARY") or "").strip() in {"1", "true", "yes"}),
        },
    }
    batch = build_batch_payload(pseudo, name=f"session-cross-{pseudo['case_id']}-drydb")
    print("\n== --dry-db(compile-only):批次载荷骨架(未发送任何请求) ==")
    print(json.dumps(sanitize_for_print(batch), ensure_ascii=False, indent=2))
    print("提示:运行载荷(create_run/context_build/tool_calls/evaluation/complete)在完整模式 + --dry-db 下打印。")


def _print_dry_db(
    report: dict[str, Any],
    artifacts: dict[str, Any],
    case_dir: Path,
    tokenizer_version: str,
) -> None:
    """完整模式 --dry-db:构造全部落库载荷并打印(脱敏),不发送任何请求。"""

    from bdlh_runtime.evaluation.session_cross_db import (
        build_run_persist_plan,
        sanitize_for_print,
    )
    from bdlh_runtime.session import serialize_session

    session = load_session(case_dir / f"{case_dir.name}.session.json")
    items = [_dry_db_system_item()] + [entry.item for entry in serialize_session(session)]
    plan = build_run_persist_plan(
        report, artifacts=artifacts, items=items, tokenizer_version=tokenizer_version,
        fixture_set_id=session.fixture_set_id,
    )
    print("\n== --dry-db:全部落库载荷(未发送任何请求) ==")
    print(json.dumps(sanitize_for_print(plan["batch"]), ensure_ascii=False, indent=2))
    for entry in plan["runs"]:
        print(f"\n-- run {entry['run_key']} --")
        print(json.dumps(sanitize_for_print(entry["payloads"]), ensure_ascii=False, indent=2, default=str))
    print(f"\n共 {len(plan['runs'])} 条运行载荷;报告工件登记:{json.dumps(sanitize_for_print(plan['report_artifact']), ensure_ascii=False)}")


def _dry_db_system_item():
    from bdlh_runtime.context import ContextClassification, ContextItem, ContextRole

    return ContextItem(
        item_id="system-prompt",
        content="(公共系统规则,见 common_prompt_hash)",
        classification=ContextClassification.REQUIRED,
        role=ContextRole.SYSTEM,
        sequence=-1000,
    )


def _save_to_db(
    report: dict[str, Any],
    artifacts: dict[str, Any],
    case_dir: Path,
    tokenizer_version: str,
) -> int:
    """--save-db:经 data 服务落库;服务不可用时给出明确错误与启动指引。"""

    from bdlh_runtime.data_client import DataClient, DataServiceError
    from bdlh_runtime.evaluation.session_cross_db import persist_session_cross_report

    base_url = os.getenv("DATA_API_BASE_URL") or "http://data:8080/internal/v1"
    session = load_session(case_dir / f"{case_dir.name}.session.json")
    artifacts_dir = os.getenv("SESSION_CROSS_ARTIFACTS_DIR") or str(_REPO_ROOT / "engine" / "var" / "artifacts")
    data = DataClient(base_url=base_url)
    try:
        result = persist_session_cross_report(
            data,
            report,
            artifacts=artifacts,
            session=session,
            tokenizer_version=tokenizer_version,
            artifacts_dir=artifacts_dir,
        )
    except DataServiceError as exc:
        print(f"\n[--save-db] data 服务不可用或拒绝请求:{exc}")
        print("启动指引:")
        print(f"  当前 DATA_API_BASE_URL={base_url}(容器内默认地址,本地运行需覆盖)")
        print("  本地启动 data 服务见 deploy/本地启动说明.md(data 固定端口 18081):")
        print('    $env:DATA_API_BASE_URL = "http://127.0.0.1:18081/internal/v1"')
        print("  同时需要 deploy/.env 中的 DATA_INTERNAL_TOKEN 与 data 服务一致。")
        print("  可先用 --dry-db 在无 data 服务环境校验载荷。")
        return 1
    print(f"\n[--save-db] 批次已落库:batch_id={result['batch_id']},共 {len(result['run_ids'])} 条运行。")
    print(f"[--save-db] 报告工件已登记(artifactType=session_cross_report),工件目录:{artifacts_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
