"""压缩用例模块:三个版本化长 Session 的上下文生成与原生运行。

数据来源只允许上下文压缩模块维护的三个长 Session(引擎 var/cases 下),
不从普通用例库读取。两种操作互不自动触发:

1. ``generate_contexts``:只生成、统计和冻结四份上下文工件——本函数结构上
   不 import AgentLoop,无法创建 Agent、Tool 或评判运行;
2. ``run_current_combo``:读取一份冻结工件,原生底座运行 1 次;
   ``run_native_context_matrix``(4×1):四份工件 × 统一原生配置。

冻结纪律:所有运行读取内容和哈希完全相同的冻结工件
(同进程直接复用编译对象;跨请求按存储工件的 compiled_context_hash
逐一校验,确定性构建哈希不一致即视为过期,提示重新生成,不静默复用)。
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bdlh_runtime.context import (
    ContextBuilder,
    ContextBuildRequest,
    ContextBuildResult,
)
from bdlh_runtime.experiments import (
    COMPRESSION_REPEAT_COUNT,
    CONTEXT_MODES,
    NATIVE_AGENT_MODE_ID,
    RunUnit,
    TestType,
    plan_native_context_runs,
    validate_repeat_count,
)
from bdlh_runtime.experiments.run_config import (
    EXECUTION_ENGINE_NATIVE_TOOL_CALLING,
    GOVERNANCE_STANDARD,
    TOOL_DELIVERY_ALL,
    ContextParams,
    LimitsConfig,
    ModelParams,
    RunConfig,
    ToolsConfig,
    hash_of,
)
from bdlh_runtime.session import (
    CompiledContext,
    SessionCompiler,
    dispatcher_from_gold,
    load_gold,
    load_session,
    load_variants,
    serialize_session,
)
from bdlh_runtime.session.compiler import STRUCTURED_TEXT_ALGO_VERSION
from bdlh_runtime.session.loader import SessionCase, SessionEvent
from bdlh_runtime.tools.catalog import ToolCard, ToolCatalog

_REPO_ROOT = Path(__file__).resolve().parents[4]
CASES_ROOT = _REPO_ROOT / "engine" / "var" / "cases"

#: 压缩用例唯一数据来源:三个版本化长 Session(普通用例库不再维护 ctx-* 长上下文用例)
COMPRESSION_SESSIONS: tuple[tuple[str, str], ...] = (
    ("ctx-session-product-evolution-01", "产品演进与需求决策"),
    ("ctx-session-context-engine-debug-01", "上下文引擎排查"),
    ("ctx-session-database-deploy-01", "数据库与部署"),
)

FINGERPRINT_VERSION = "compression-fingerprint-v1"

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


class CompressionSessionError(ValueError):
    """未知的压缩 Session 或非法操作参数。"""


class StaleContextArtifactError(RuntimeError):
    """冻结工件缺失或与当前 Session/参数不一致,必须先重新生成上下文。"""


def session_case_dir(session_id: str) -> Path:
    return CASES_ROOT / session_id


def _load_session_bundle(session_id: str) -> tuple[SessionCase, dict[str, Any], Path]:
    if session_id not in {row[0] for row in COMPRESSION_SESSIONS}:
        raise CompressionSessionError(
            f"未知压缩 Session:{session_id!r};可用:{[row[0] for row in COMPRESSION_SESSIONS]}"
        )
    case_dir = session_case_dir(session_id)
    session = load_session(case_dir / f"{session_id}.session.json")
    variants = load_variants(case_dir / f"{session_id}.variants.json")
    return session, variants, case_dir


def current_event_of(session: SessionCase) -> SessionEvent:
    """最新一条有效 user_message 事件(作为当前输入,只发送一次,不进历史压缩)。"""
    for event in reversed(session.events):
        if event.type == "user_message":
            return event
    raise CompressionSessionError(f"Session {session.session_id} 没有用户消息事件")


def current_event_info(session: SessionCase) -> dict[str, str]:
    event = current_event_of(session)
    return {
        "current_event_id": event.event_id,
        "current_message": event.content,
        "current_message_hash": f"sha256:{hashlib.sha256(event.content.encode('utf-8')).hexdigest()}",
    }


def compute_fingerprint(session: SessionCase, variants: dict[str, Any], tokenizer_version: str) -> dict[str, Any]:
    """工件复用键:任一字段变化后旧工件不能复用,页面提示重新生成。"""
    variant_rows = sorted(
        (
            {
                "variant_id": str(row["variant_id"]),
                "strategy": str(row.get("strategy") or ""),
                "strategy_version": str(row.get("strategy_version") or ""),
                "token_budget": int(row.get("token_budget") or 0),
            }
            for row in variants.get("context_variants") or []
        ),
        key=lambda row: row["variant_id"],
    )
    return {
        "fingerprint_version": FINGERPRINT_VERSION,
        "session_id": session.session_id,
        "session_version": session.session_version,
        "source_session_hash": session.source_hash,
        **current_event_info(session),
        "tool_catalog_version": session.tool_catalog_version or "",
        "fixture_set_id": session.fixture_set_id or "",
        "algo_version": STRUCTURED_TEXT_ALGO_VERSION,
        "tokenizer_version": tokenizer_version,
        "llm_summary": bool((variants.get("common_conditions") or {}).get("llm_summary")),
        "variants": variant_rows,
    }


@dataclass
class ContextGenerationResult:
    """「生成四份上下文」的结果:只有上下文工件,没有任何 Agent 运行。"""

    session_id: str
    session_version: int
    fingerprint: dict[str, Any]
    artifacts: dict[str, dict[str, Any]]  # variant_id → 公开工件 payload
    stats: dict[str, Any]
    #: 结构保证:本操作产生的 Agent/工具/评判运行数恒为 0(不经过任何 Agent 路径)
    agent_runs_created: int = 0
    generated_at: str = ""


def generate_contexts(
    session_id: str,
    *,
    write: bool = True,
    llm_summary: bool = False,
    compiler: SessionCompiler | None = None,
) -> ContextGenerationResult:
    """操作一:生成四份上下文。不调用 Agent、Tools 或最终回答评判。"""
    from bdlh_runtime.engine.loop import load_prompt

    session, variants, case_dir = _load_session_bundle(session_id)
    instance = compiler or SessionCompiler.from_env(llm_summary=llm_summary)
    common_rules = load_prompt("system_base.md", "scene_chat.md")

    artifacts: dict[str, dict[str, Any]] = {}
    for variant in variants.get("context_variants") or []:
        variant_id = str(variant["variant_id"])
        started = time.perf_counter()
        try:
            compiled = instance.compile(session, variant, common_rules=common_rules)
            payload = compiled.to_payload()
            payload["status"] = "COMPLETE"
        except ValueError as exc:  # full-session 超窗等 → 记为无效上下文,不静默截断
            payload = {
                "case_id": session.session_id,
                "case_version": session.session_version,
                "source_session_hash": session.source_hash,
                "variant_id": variant_id,
                "strategy_version": str(variant.get("strategy_version") or ""),
                "token_budget": int(variant.get("token_budget") or 0),
                "status": "INVALID",
                "error": str(exc),
            }
        payload["compile_wall_ms"] = round((time.perf_counter() - started) * 1000)
        artifacts[variant_id] = payload

    fingerprint = compute_fingerprint(session, variants, instance.tokenizer_version)
    result = ContextGenerationResult(
        session_id=session.session_id,
        session_version=session.session_version,
        fingerprint=fingerprint,
        artifacts=artifacts,
        stats={
            "variant_count": len(artifacts),
            "complete_count": sum(1 for row in artifacts.values() if row.get("status") == "COMPLETE"),
            "original_tokens": {vid: row.get("original_tokens") for vid, row in artifacts.items()},
            "working_tokens": {vid: row.get("working_tokens") for vid, row in artifacts.items()},
        },
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )
    if write:
        out_dir = case_dir / "compiled"
        out_dir.mkdir(parents=True, exist_ok=True)
        for variant_id, payload in artifacts.items():
            (out_dir / f"{variant_id}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        (out_dir / "fingerprint.json").write_text(
            json.dumps(fingerprint, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return result


def compile_variants(
    session: SessionCase,
    variants: dict[str, Any],
    *,
    llm_summary: bool = False,
    compiler: SessionCompiler | None = None,
) -> dict[str, CompiledContext]:
    """编译并返回四份工件对象(同批冻结;运行阶段复用,不重新摘要/压缩)。"""
    from bdlh_runtime.engine.loop import load_prompt

    instance = compiler or SessionCompiler.from_env(llm_summary=llm_summary)
    common_rules = load_prompt("system_base.md", "scene_chat.md")
    compiled: dict[str, CompiledContext] = {}
    for variant in variants.get("context_variants") or []:
        compiled[str(variant["variant_id"])] = instance.compile(session, variant, common_rules=common_rules)
    return compiled


def _load_frozen_batch(session_id: str) -> tuple[SessionCase, dict[str, Any], dict[str, CompiledContext]]:
    """读取冻结工件批次:确定性重算 + 与存储工件哈希逐一校验。

    确定性构建(默认抽取式摘要)在输入相同时结果可复现;哈希一致即证明
    读到的是同一份冻结工件。哈希不一致或指纹变化 → StaleContextArtifactError,
    绝不静默用旧工件继续运行,也不自动开始重新压缩。
    """
    session, variants, case_dir = _load_session_bundle(session_id)
    compiled_dir = case_dir / "compiled"
    fingerprint_path = compiled_dir / "fingerprint.json"
    if not fingerprint_path.is_file():
        raise StaleContextArtifactError(
            f"Session {session_id} 尚未生成四份上下文工件,请先执行「生成四份上下文」"
        )
    stored_fingerprint = json.loads(fingerprint_path.read_text(encoding="utf-8"))
    instance = SessionCompiler.from_env()
    current_fingerprint = compute_fingerprint(session, variants, instance.tokenizer_version)
    differing = [
        key
        for key in (
            "source_session_hash", "session_version", "current_event_id",
            "current_message_hash", "tokenizer_version", "algo_version",
        )
        if stored_fingerprint.get(key) != current_fingerprint.get(key)
    ]
    if differing:
        raise StaleContextArtifactError(
            f"Session {session_id} 的 {differing} 已变化,旧工件不能复用;请先重新生成四份上下文"
        )
    if stored_fingerprint.get("llm_summary"):
        raise StaleContextArtifactError(
            f"Session {session_id} 的工件使用 LLM 摘要生成,跨请求复用需在同一任务内先执行生成;请重新生成"
        )
    compiled = compile_variants(session, variants, compiler=instance)
    for variant_id, artifact in compiled.items():
        stored_path = compiled_dir / f"{variant_id}.json"
        if not stored_path.is_file():
            raise StaleContextArtifactError(f"工件 {session_id}/{variant_id} 缺失,请重新生成四份上下文")
        stored = json.loads(stored_path.read_text(encoding="utf-8"))
        if stored.get("compiled_context_hash") != artifact.compiled_context_hash:
            raise StaleContextArtifactError(
                f"工件 {session_id}/{variant_id} 哈希与当前构建不一致(Session/参数已变化),请重新生成四份上下文"
            )
    return session, variants, compiled


@dataclass
class CellRunResult:
    """压缩矩阵一格的一次运行样本(每格只有一个样本,页面写「本次结果」)。"""

    unit_id: str
    context_variant: str
    agent_mode_id: str
    repeat_index: int
    answer: str
    tool_calls: list[dict[str, Any]]
    judgment: dict[str, Any]
    validity: str
    duration_ms: int
    stop_reason: str
    actual_agent_steps: int
    context_artifact_hash: str
    error: str | None = None
    #: 本格运行的配置快照哈希(配置体见批次 run_configs,按 f"{variant}:{mode}" 索引)
    config_hash: str = ""


def build_compression_run_configs(
    session: SessionCase,
    compiled: dict[str, CompiledContext],
    max_agent_steps: int,
    *,
    model_id: str = "configured-model",
    tokenizer_version: str = "conservative-chars4-v1",
    agent_mode_ids: tuple[str, ...] = (NATIVE_AGENT_MODE_ID,),
) -> dict[str, RunConfig]:
    """为压缩运行的每格构建运行配置快照(阶段 A3)。

    统一原生底座(4×1):同一执行引擎、治理与装载,唯一自变量是
    ``context_strategy``。
    """
    configs: dict[str, RunConfig] = {}
    for variant_id, artifact in compiled.items():
        for mode in agent_mode_ids:
            if mode != NATIVE_AGENT_MODE_ID:
                raise CompressionSessionError(f"未知 Agent 实现编号:{mode!r}")
            config = RunConfig(
                execution_engine=EXECUTION_ENGINE_NATIVE_TOOL_CALLING,
                tool_delivery=TOOL_DELIVERY_ALL,
                governance_profile=GOVERNANCE_STANDARD,
                context_strategy=str(artifact.strategy),
                model=ModelParams(model_id=model_id),
                limits=LimitsConfig(
                    max_agent_steps=max_agent_steps,
                    max_tool_calls=max(0, max_agent_steps + 2),
                ),
                tools=ToolsConfig(catalog_version="session-mock-v1"),
                context=ContextParams(
                    token_budget=int(artifact.token_budget or 0),
                    tokenizer_version=tokenizer_version,
                ),
                fixture_version=str(session.fixture_set_id or "session-gold-v1"),
            )
            config.validate()
            configs[f"{session.session_id}:{variant_id}:{mode}"] = config
    return configs


#: 单元执行器协议:async (session, artifact, agent_mode_id, run_key, max_agent_steps) -> raw dict
CellRunner = Callable[..., Any]


async def _default_cell_runner(
    session: SessionCase,
    artifact: CompiledContext,
    agent_mode_id: str,
    run_key: str,
    max_agent_steps: int,
    *,
    llm: Any,
) -> dict[str, Any]:
    """生产执行器:统一原生 AgentLoop 读冻结工件运行一次。"""
    import asyncio as _asyncio
    import os

    from bdlh_runtime.context import ConservativeTokenCounter
    from bdlh_runtime.engine.loop import AgentLoop, AgentTurn, _tool_schema_tokens

    gold = load_gold(session_case_dir(session.session_id) / "gold" / f"{session.session_id}.gold.json")
    dispatcher = dispatcher_from_gold(gold)

    async def executor(name: str, arguments: dict[str, Any]) -> Any:
        result = await dispatcher(name, arguments)
        return result

    call_log: list[tuple[str, dict[str, Any]]] = []

    async def recording_executor(name: str, arguments: dict[str, Any]) -> Any:
        call_log.append((name, dict(arguments)))
        return await executor(name, arguments)

    catalog = session_tool_catalog(list(session.visible_tools))
    cards = catalog.list()
    schema_tokens = _tool_schema_tokens(cards, ConservativeTokenCounter())
    timeout_s = float(os.getenv("EVAL_RUN_TIMEOUT_S", "300"))
    started = time.perf_counter()
    stop_reason = ""
    actual_steps = 0
    try:
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
        frozen_ids = (
            ("system-prompt",)
            + tuple(item.item_id for item in turn.context_entries)
            + ("current-question",)
        )
        loop = AgentLoop(
            llm=llm,
            catalog=catalog,
            executor=recording_executor,
            # 统一原生底座(D1):all 装载,唯一自变量是上下文方式
            tool_loading="all",
            max_agent_steps=max_agent_steps,
            context_builder=FrozenContextBuilder(ContextBuilder(), frozen_ids, artifact.build_result),
        )
        agent_result = await _asyncio.wait_for(loop.run(turn), timeout=timeout_s)
        answer = agent_result.answer
        error = agent_result.context_error if agent_result.degraded else None
        stop_reason = agent_result.stop_reason or ""
        actual_steps = agent_result.actual_steps
    except TimeoutError:
        answer, error, stop_reason = "", "运行超时:单运行熔断", "TIMEOUT"
    return {
        "answer": answer,
        "error": error,
        "tool_calls": [{"tool": name, "arguments": args} for name, args in call_log],
        "stop_reason": stop_reason,
        "actual_agent_steps": actual_steps,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "mock_records": [record.to_payload() for record in dispatcher.call_log],
    }


async def run_current_combo(
    session_id: str,
    context_variant: str,
    agent_mode_id: str,
    *,
    artifacts: dict[str, CompiledContext] | None = None,
    llm: Any = None,
    max_agent_steps: int | None = None,
    cell_runner: CellRunner | None = None,
) -> CellRunResult:
    """操作二:一份冻结工件 × 一种 Agent,只运行 1 次。"""
    from bdlh_runtime.experiments import default_max_agent_steps

    validate_repeat_count(TestType.COMPRESSION_CASE, COMPRESSION_REPEAT_COUNT)
    steps = max_agent_steps or default_max_agent_steps()
    if artifacts is not None:
        session, variants, _ = _load_session_bundle(session_id)
        compiled = artifacts
    else:
        session, variants, compiled = _load_frozen_batch(session_id)
    if context_variant not in compiled:
        raise CompressionSessionError(
            f"未知上下文方式 {context_variant!r};可用:{sorted(compiled)}"
        )
    if agent_mode_id != NATIVE_AGENT_MODE_ID:
        raise CompressionSessionError(
            f"未知 Agent 实现编号:{agent_mode_id!r};可用:{NATIVE_AGENT_MODE_ID}"
        )
    artifact = compiled[context_variant]
    runner = cell_runner or _default_cell_runner
    run_key = f"{session_id}:{context_variant}:{agent_mode_id}"
    configs = build_compression_run_configs(session, compiled, steps)
    raw = await runner(session, artifact, agent_mode_id, run_key, steps, llm=llm)
    return _assemble_cell_result(
        session, artifact, context_variant, agent_mode_id, raw, compiled,
        config_hash=configs[run_key].config_hash,
    )


async def run_native_context_matrix(
    session_id: str,
    *,
    artifacts: dict[str, CompiledContext] | None = None,
    llm: Any = None,
    max_agent_steps: int | None = None,
    cell_runner: CellRunner | None = None,
    should_stop: Callable[[], bool] | None = None,
    inter_cell_delay_s: float = 0.0,
) -> dict[str, Any]:
    """新默认上下文运行计划(混合路线 D1):4 种上下文 × 1 种固定原生配置(4×1)。

    唯一自变量是 ``context_strategy``;变体复用同一 Session 版本、当前事件、
    工具目录和 Mock;不创建 8 格。
    """
    from bdlh_runtime.experiments import default_max_agent_steps

    steps = max_agent_steps or default_max_agent_steps()
    if artifacts is not None:
        session, variants, _ = _load_session_bundle(session_id)
        compiled = artifacts
    else:
        session, variants, compiled = _load_frozen_batch(session_id)

    units: list[RunUnit] = plan_native_context_runs(session_id)
    cells: list[CellRunResult] = []
    skipped: list[str] = []
    runner = cell_runner or _default_cell_runner
    run_configs = build_compression_run_configs(
        session, compiled, steps, agent_mode_ids=(NATIVE_AGENT_MODE_ID,)
    )
    for unit in units:
        if should_stop is not None and should_stop():
            skipped.append(unit.unit_id)
            continue
        artifact = compiled[unit.context_variant or ""]
        raw = await runner(
            session, artifact, unit.agent_mode_id, unit.unit_id, steps, llm=llm
        )
        cells.append(
            _assemble_cell_result(
                session, artifact, unit.context_variant or "", unit.agent_mode_id, raw, compiled,
                config_hash=run_configs[unit.unit_id].config_hash,
            )
        )
        if inter_cell_delay_s:
            import asyncio as _asyncio

            await _asyncio.sleep(inter_cell_delay_s)

    fixed_conditions = {
        "session_id": session.session_id,
        "session_version": session.session_version,
        "source_session_hash": session.source_hash,
        "repeat_count": COMPRESSION_REPEAT_COUNT,
        "max_agent_steps": steps,
        "context_variants": list(CONTEXT_MODES),
        "agent_mode_ids": [NATIVE_AGENT_MODE_ID],
        "independent_variable": ["context_strategy"],
        "experiment_definition": "context-strategy-comparison",
        "experiment_definition_note": "4×1:同一原生 Tool Calling 底座,唯一自变量是上下文方式",
    }
    return {
        "test_type": TestType.COMPRESSION_CASE.value,
        "session_id": session_id,
        "session_version": session.session_version,
        "repeat_count": COMPRESSION_REPEAT_COUNT,
        "max_agent_steps": steps,
        "unit_count": len(units),
        "cells": [cell.__dict__ for cell in cells],
        "skipped_unit_ids": skipped,
        "frozen_artifact_hashes": {
            variant_id: artifact.compiled_context_hash for variant_id, artifact in compiled.items()
        },
        "run_configs": {key: config.config_payload_with_hash() for key, config in run_configs.items()},
        "fixed_conditions": fixed_conditions,
        "fixed_conditions_hash": hash_of(fixed_conditions),
    }


def _assemble_cell_result(
    session: SessionCase,
    artifact: CompiledContext,
    context_variant: str,
    agent_mode_id: str,
    raw: dict[str, Any],
    compiled_batch: dict[str, CompiledContext],
    *,
    config_hash: str = "",
) -> CellRunResult:
    from dataclasses import asdict

    from bdlh_runtime.evaluation.run_telemetry import classify_failure, validity_of
    from bdlh_runtime.session import judge_session_run

    status, category = classify_failure(raw.get("error"))
    gold = load_gold(session_case_dir(session.session_id) / "gold" / f"{session.session_id}.gold.json")
    judgment = judge_session_run(
        compiled=artifact,
        gold=gold,
        tool_calls=[(row["tool"], row["arguments"]) for row in raw.get("tool_calls") or []],
        answer=str(raw.get("answer") or ""),
        visible_tools=list(session.visible_tools),
        validity=validity_of(status),
        error_category=category,
    )
    return CellRunResult(
        unit_id=f"{session.session_id}:{context_variant}:{agent_mode_id}",
        context_variant=context_variant,
        agent_mode_id=agent_mode_id,
        repeat_index=0,
        answer=str(raw.get("answer") or ""),
        tool_calls=list(raw.get("tool_calls") or []),
        judgment=asdict(judgment),
        validity=validity_of(status),
        duration_ms=int(raw.get("duration_ms") or 0),
        stop_reason=str(raw.get("stop_reason") or ""),
        actual_agent_steps=int(raw.get("actual_agent_steps") or 0),
        context_artifact_hash=artifact.compiled_context_hash,
        error=raw.get("error"),
        config_hash=config_hash,
    )


def public_session_overview() -> list[dict[str, Any]]:
    """压缩用例页的三个 Session 概览(公开字段,不含 gold 与评判配置)。"""
    from bdlh_runtime.context.token_count import ConservativeTokenCounter

    counter = ConservativeTokenCounter()
    overview: list[dict[str, Any]] = []
    for session_id, title in COMPRESSION_SESSIONS:
        session, variants, _ = _load_session_bundle(session_id)
        info = current_event_info(session)
        overview.append(
            {
                "session_id": session_id,
                "title": title,
                "session_version": session.session_version,
                "event_count": len(session.events),
                "user_message_count": sum(1 for event in session.events if event.type == "user_message"),
                "tool_pair_count": sum(1 for event in session.events if event.type == "tool_call"),
                "current_event_id": info["current_event_id"],
                "current_message_excerpt": info["current_message"][:120],
                "estimated_tokens": sum(counter.count(event.content) for event in session.events),
                "context_modes": list(CONTEXT_MODES),
                "tool_catalog_version": session.tool_catalog_version or "",
                "fixture_set_id": session.fixture_set_id or "",
            }
        )
    return overview
