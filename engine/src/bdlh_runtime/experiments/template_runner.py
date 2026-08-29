"""模板批次统一执行底座(混合路线阶段 B2)。

所有正式单变量模板经本模块在**同一个**原生 Tool Calling ``AgentLoop`` 上
运行:两个治理变体(off/standard)使用相同消息构建、工具绑定、停止规则、
最大轮次和最终回答流程,只改变治理配置;两个变体共用同一实现分支。

Mock-only 结构保证:执行器固定为 ``FrozenFixtureExecutor``(或测试注入的
等价 Mock),不发送外部请求、不写外部文件;即使治理关闭,写工具也只能
进入无外部副作用的 Mock 执行器。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from dataclasses import dataclass, field
from typing import Any

from bdlh_runtime.context import ConservativeTokenCounter
from bdlh_runtime.engine.loader import ToolLoader
from bdlh_runtime.engine.loop import AgentLoop, AgentTurn, _tool_schema_tokens
from bdlh_runtime.experiments.fixture_executor import FrozenFixtureExecutor
from bdlh_runtime.experiments.fixture_hash import catalog_schema_hash
from bdlh_runtime.experiments.run_config import (
    GOVERNANCE_OFF,
    RunConfig,
)
from bdlh_runtime.experiments.templates import PlannedRun, TemplateBatchPlan
from bdlh_runtime.experiments.tool_catalog_snapshot import tool_manifests
from bdlh_runtime.guardrails.confirmations import ConfirmationProvider
from bdlh_runtime.tools.catalog import ToolCard, ToolCatalog
from bdlh_runtime.tools.search import ToolSearchIndex

#: 模板上下文变体 → ContextStrategy 枚举值(recent-window 的枚举名是 recent-n)
CONTEXT_STRATEGY_MAP = {
    "full": "full",
    "recent-window": "recent-n",
    "single-summary": "single-summary",
    "budgeted": "budgeted",
    "budgeted-session": "budgeted",
    "full-session": "full",
}


@dataclass
class NativeRunRecord:
    """一次模板运行的完整记录(统一事件结构,不因变体缺失关键字段)。

    自可观测性改造起(设计 §5.2),``events``/``model_calls``/``tool_calls``/
    ``guardrail_checks`` 与 eval 链路同构产出:model_calls 保留逐轮消息与
    Tool Schema/参数三态快照,tool_calls 为带调用关联的 recorder 明细行。
    批次报告保存点负责剥离消息正文防膨胀,内存记录保持完整。
    """

    run_id: str
    variant_label: str
    repeat_index: int
    config_hash: str
    governance_profile: str
    answer: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    audits: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""
    actual_agent_steps: int = 0
    duration_ms: int = 0
    validity: str = "VALID"
    error: str | None = None
    visible_tools: list[str] = field(default_factory=list)
    tool_schema_hash: str = ""
    tool_schema_tokens: int = 0
    search_log: list[dict[str, Any]] = field(default_factory=list)
    bypassed_event_count: int = 0
    observations: list[dict[str, Any]] = field(default_factory=list)
    #: eligible catalog(完整目录 − 排除项)的内容哈希;all/search 组一致(C1/C3)
    eligible_catalog_hash: str = ""
    #: TOOL_NOT_VISIBLE 事件及随后是否恢复(再次搜索后装载并调用成功)
    tool_not_visible_events: list[dict[str, Any]] = field(default_factory=list)
    #: 实际发给 SDK 的模型参数(逐运行记录,防止「配置四种温度、请求全是 0.1」)
    applied_model_params: dict[str, Any] = field(default_factory=dict)
    #: ── Token 计量(RecordingLLM 逐请求抄录响应 usage;账单口径) ──────────
    input_tokens: int = 0
    output_tokens: int = 0
    #: 响应缺失 usage 元数据、按本地计数器估算时为 True(不以 0 冒充实测)
    tokens_estimated: bool = False
    #: 逐请求完整明细(含消息快照/当轮 Tool Schema/参数三态;报告保存点剥离正文)
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    #: run_events 事件流(run.started → … → run.completed,全局 sequence)
    events: list[dict[str, Any]] = field(default_factory=list)
    #: guardrail 检查明细(含 DENIED 拦截关联)
    guardrail_checks: list[dict[str, Any]] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return dict(self.__dict__)


def build_llm_for_config(run_config: RunConfig, *, model: str | None = None) -> Any:
    """按一份 RunConfig 构建本次运行的模型客户端(温度模板修复的核心)。

    每次调用创建**独立**实例,temperature/max_output_tokens/
    parallel_tool_calls 来自该运行的生效值——同一批次的不同温度变体
    各自拿到自己的客户端,不再共享默认 0.1 的单实例。
    env 缺失时 create_llm 返回 None(调用方降级,如实记录)。
    """
    from bdlh_runtime.infra.llm import create_llm

    params = run_config.model
    temperature = (
        params.temperature_effective
        if params.temperature_effective is not None
        else (params.temperature_requested if params.temperature_requested is not None else 0.1)
    )
    return create_llm(
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
        model=model or os.getenv("LLM_MODEL", "Qwen/Qwen3.6-35B-A3B"),
        temperature=float(temperature),
        max_output_tokens=params.max_output_tokens,
        parallel_tool_calls=params.parallel_tool_calls,
        # P0-3:重试上限来自冻结运行配置;None 时 SDK 默认重试会把一次
        # 逻辑调用放大为多次 HTTP 请求,配置与实际行为不一致
        max_retries=run_config.limits.llm_retry_count,
    )


def applied_params_of(llm: Any) -> dict[str, Any]:
    """从模型客户端读回实际生效参数(证据口径;读不到的键不臆造)。"""
    if llm is None:
        return {}
    applied: dict[str, Any] = {}
    temperature = getattr(llm, "temperature", None)
    if temperature is not None:
        applied["temperature"] = temperature
    max_tokens = getattr(llm, "max_tokens", None)
    if max_tokens is not None:
        applied["max_output_tokens"] = max_tokens
    model_kwargs = getattr(llm, "model_kwargs", None) or {}
    if "parallel_tool_calls" in model_kwargs:
        applied["parallel_tool_calls"] = bool(model_kwargs["parallel_tool_calls"])
    max_retries = getattr(llm, "max_retries", None)
    if max_retries is not None:
        applied["max_retries"] = max_retries
    return applied


#: requested 了但适配器未发送时的默认原因文案(参数三态,设计 §4.1)
_PARAM_NOT_SENT_NOTES = {
    "temperature": "当前适配器未发送该参数",
    "top_p": "当前适配器未发送该参数",
    "reasoning_effort": "当前适配器未接线该参数",
    "seed": "当前适配器未发送该参数",
    "tool_choice": "当前适配器未显式发送,由模型自行决定",
    "parallel_tool_calls": "当前适配器未发送该参数",
    "max_output_tokens": "当前适配器未发送该参数",
}


def model_param_snapshots(run_config: RunConfig, applied_params: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """参数三态快照(requested / sent / unsupported,可观测性设计 §4.1)。

    requested 来自冻结运行配置;sent 来自模型客户端属性回读(applied_params,
    证据口径,读不到的键不臆造);unsupported 为请求了但未实际发送的字段
    及原因,并合入配置声明的 unsupported_reasons("字段: 原因"格式)。
    """
    params = run_config.model
    requested = {
        key: value
        for key, value in {
            "temperature": params.temperature_requested,
            "top_p": params.top_p_requested,
            "reasoning_effort": params.reasoning_effort_requested,
            "seed": params.seed_requested,
            "max_output_tokens": params.max_output_tokens,
            "tool_choice": params.tool_choice,
            "parallel_tool_calls": params.parallel_tool_calls,
        }.items()
        if value is not None
    }
    sent = dict(applied_params or {})
    unsupported: dict[str, Any] = {
        key: _PARAM_NOT_SENT_NOTES.get(key, "当前适配器未发送该参数") for key in requested if key not in sent
    }
    for reason in params.unsupported_reasons:
        name, _, note = str(reason).partition(": ")
        if name:
            unsupported.setdefault(name, note or "配置声明不支持")
    return {"requested": requested, "sent": sent, "unsupported": unsupported}


def build_template_catalog(visible_tools: tuple[str, ...] | list[str]) -> tuple[ToolCatalog, list[ToolCard]]:
    """从对比目录快照构建本批工具目录(eligible catalog 由调用方计算)。

    search 提供方式需要 ``search_tools`` 元工具:不在快照名单内时补登记
    (Schema 与正式目录同一投影),否则 search 装载无法向模型提供检索入口。
    """
    from bdlh_runtime.experiments.tool_catalog_snapshot import build_comparison_catalog
    from bdlh_runtime.tools.catalog import _parameters_for

    catalog, ordered = build_comparison_catalog(tuple(visible_tools))
    if not catalog.contains("search_tools"):
        catalog.register(
            ToolCard(
                name="search_tools",
                description="按自然语言描述从 eligible catalog(完整目录减排除项)检索工具,"
                "返回候选名称、说明与排名;命中后装载进后续上下文。",
                parameters=_parameters_for("search_tools", ("query",)),
                required_scope=[],
            )
        )
    return catalog, ordered


async def run_native_agent(
    *,
    run_config: RunConfig,
    message: str,
    visible_tools: tuple[str, ...] | list[str],
    llm: Any,
    fixtures: list[dict[str, Any]] | None = None,
    history: list[dict[str, str]] | None = None,
    scene_tag: str = "general",
    authenticated: bool = True,
    user_id: str = "template-runner",
    fixture_version: str | int = 1,
    confirmation_provider: ConfirmationProvider | None = None,
    encoder: Any | None = None,
    run_id: str | None = None,
    executor: Any | None = None,
    variant_label: str = "",
    repeat_index: int = 0,
    timeout_seconds: float | None = None,
    template_id: str = "",
) -> NativeRunRecord:
    """按一份 RunConfig 在统一原生循环上执行一次运行。

    - ``tool_delivery`` = all/search 经 ToolLoader 落地;search 使用
      catalog 基座(完整目录 − 排除项)且不回退;
    - 治理档位与写确认提供方透传给中间件;
    - 执行器固定 Mock(冻结 fixture);``executor`` 参数仅供测试注入替身;
    - 遥测:per-run ``RunRecorder`` 统一收集 events/model_calls(含逐轮
      消息、当轮 Tool Schema、参数三态)/tool_calls(带调用关联)/
      guardrail_checks,与 eval 链路同一落库协议(设计 §5.2)。
    """
    run_config.validate()
    # 逐运行模型客户端:llm=None 时按本运行生效参数构建独立实例
    # (温度变体各自拿到自己的温度;共享外部实例仅用于测试注入 Fake)
    per_run_llm = llm if llm is not None else build_llm_for_config(run_config)
    applied_params = applied_params_of(per_run_llm)
    llm_missing = llm is None and per_run_llm is None
    model_id = str(run_config.model.model_id or "")
    run_id_value = run_id or f"native:{run_config.config_hash[:12]}"
    from bdlh_runtime.evaluation.run_telemetry import (
        RecordingExecutor,
        RecordingLLM,
        RunRecorder,
        record_governance_audits,
    )

    # per-run recorder(与 eval 链路同构;run.started 在构造时发出)
    recorder = RunRecorder.for_template_run(
        run_id=run_id_value,
        model=model_id,
        variant_label=variant_label,
        repeat_index=repeat_index,
        message=message,
        context_strategy=str(run_config.context_strategy),
        config_hash=run_config.config_hash,
        template_id=template_id,
    )
    recorder.attach_model_params(**model_param_snapshots(run_config, applied_params))
    loop_llm = RecordingLLM(per_run_llm, recorder, model_id) if per_run_llm is not None else None
    catalog, ordered_cards = build_template_catalog(visible_tools)
    mock_executor = executor or FrozenFixtureExecutor(fixtures or [], fixture_version=fixture_version)
    # RecordingExecutor 记 tool.requested/completed、关联发起模型调用与 call_id;
    # call_records 等属性经 __getattr__ 透传,批次报告口径不变
    recorded_executor = RecordingExecutor(mock_executor, recorder)
    loader = ToolLoader(
        catalog,
        tool_loading=run_config.tool_delivery,
        excluded_tools=frozenset(run_config.tools.excluded_tools),
        encoder=encoder,
        # 正式口径:search 候选 = 完整目录 − 排除项(catalog 基座),不回退
        search_base="catalog",
        fallback_policy="none",
    )
    loop = AgentLoop(
        llm=loop_llm,
        catalog=catalog,
        executor=recorded_executor,
        loader=loader,
        max_agent_steps=run_config.limits.max_agent_steps,
        max_tool_calls=run_config.limits.max_tool_calls,
        max_calls_per_tool=run_config.limits.max_calls_per_tool,
        governance_profile=run_config.governance_profile,
        confirmation_provider=confirmation_provider,
        search_top_k=run_config.tools.search_top_k,
    )
    strategy = CONTEXT_STRATEGY_MAP.get(run_config.context_strategy, run_config.context_strategy)
    turn = AgentTurn(
        user_id=user_id,
        message=message,
        scene_tag=scene_tag,
        authenticated=authenticated,
        history=list(history or []),
        run_id=run_id_value,
        context_strategy=strategy,
        token_budget=run_config.context.token_budget,
    )
    eligible_manifests = [
        {"name": card.name, "description": card.description, "parameters": card.parameters}
        for card in loader.eligible_catalog()
    ]
    started = time.perf_counter()
    timeout = timeout_seconds if timeout_seconds is not None else float(run_config.limits.agent_timeout_seconds)
    loaded_names: tuple[str, ...] = ()
    audit_objects: list[Any] = []
    try:
        result = await asyncio.wait_for(loop.run(turn), timeout=timeout)
        answer = result.answer
        error = result.context_error if result.degraded else None
        if llm_missing:
            error = error or (
                "LLM_UNAVAILABLE: api key 或 base_url 未配置(create_llm 返回 None),本运行未执行任何模型调用"
            )
        stop_reason = result.stop_reason or ""
        actual_steps = result.actual_steps
        audit_objects = list(result.audits)
        audits = [audit.model_dump() for audit in result.audits]
        observations = [
            obs.model_dump(mode="json") if hasattr(obs, "model_dump") else dict(obs)
            for obs in result.observations
        ]
        # 实际装载集合(最后一轮 bind_tools 的真源):排除项/搜索动态装载/
        # 每轮变化都以它为准,不用初始完整列表冒充(混合路线证据口径修正)
        loaded_names = tuple(result.loaded_tools or ())
        if getattr(result, "context_report", None) is not None:
            recorder.record_context(
                {
                    "strategy": strategy,
                    "contextBuildMs": int(getattr(result, "context_build_ms", 0) or 0),
                    "contextRebuilds": int(getattr(result, "context_rebuilds", 0) or 0),
                }
            )
    except TimeoutError:
        answer, error, stop_reason, actual_steps = "", "运行超时:单运行熔断", "TIMEOUT", 0
        audits, observations = [], []
    # 实际装载集合(排除项/搜索动态装载都以它为准);快路径/超时无 bind_tools 时如实为空
    actual_cards = [catalog.get(name) for name in loaded_names if catalog.contains(name)] if loaded_names else []
    actual_manifests = tool_manifests(actual_cards)
    from bdlh_runtime.evaluation.run_telemetry import classify_failure, validity_of

    status, category = classify_failure(error)
    # 治理审计 → guardrail_checks/DENIED 工具行(与 eval 链路同口径;
    # 超时路径无审计对象,如实跳过)
    if audit_objects:
        record_governance_audits(recorder, audit_objects, observations)
    recorder.complete(status=status, error_category=category or None, error_text=error)
    call_records = list(getattr(mock_executor, "call_records", []) or [])
    model_call_rows = [row.to_payload() for row in recorder.record.model_calls]
    tool_call_rows = [row.to_payload() for row in recorder.record.tool_calls]
    guardrail_rows = [row.to_payload() for row in recorder.record.guardrail_checks]
    record = NativeRunRecord(
        run_id=turn.run_id,
        variant_label=variant_label,
        repeat_index=repeat_index,
        config_hash=run_config.config_hash,
        governance_profile=run_config.governance_profile,
        answer=str(answer or ""),
        tool_calls=tool_call_rows,
        audits=audits,
        stop_reason=stop_reason,
        actual_agent_steps=actual_steps,
        duration_ms=round((time.perf_counter() - started) * 1000),
        validity=validity_of(status),
        error=error,
        # 证据口径:visible_tools/Schema 哈希/Token 均为实际装载集合;
        # 初始完整目录另记 eligible_catalog_hash,二者分开
        visible_tools=list(loaded_names),
        tool_schema_hash=catalog_schema_hash(actual_manifests) if actual_manifests else "",
        tool_schema_tokens=_tool_schema_tokens(actual_cards, ConservativeTokenCounter()) if actual_cards else 0,
        search_log=list(loader.search_log),
        bypassed_event_count=sum(1 for row in audits if row.get("bypassed")),
        observations=observations,
        eligible_catalog_hash=catalog_schema_hash(eligible_manifests),
        tool_not_visible_events=_not_visible_events(audits, tool_call_rows),
        applied_model_params=applied_params,
        input_tokens=sum(int(row.get("inputTokens") or 0) for row in model_call_rows),
        output_tokens=sum(int(row.get("outputTokens") or 0) for row in model_call_rows),
        tokens_estimated=any(row.tokens_estimated for row in recorder.record.model_calls),
        model_calls=model_call_rows,
        events=list(recorder.record.events),
        guardrail_checks=guardrail_rows,
    )
    if category:
        record.error = record.error or category
    return record


def _not_visible_events(audits: list[dict[str, Any]], tool_call_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """提取 TOOL_NOT_VISIBLE 拒绝事件及恢复情况(后续同工具是否成功调用)。"""
    events: list[dict[str, Any]] = []
    for row in audits:
        if row.get("audit_code") != "TOOL_NOT_VISIBLE":
            continue
        tool = str(row.get("tool_name") or "")
        recovered = any(str(call.get("toolName")) == tool for call in tool_call_rows)
        events.append(
            {
                "tool": tool,
                "audit_code": "TOOL_NOT_VISIBLE",
                "recovered": recovered,
                "recovery_note": "未加载工具被拒绝执行;模型再次搜索装载后可恢复" if recovered else "未恢复",
            }
        )
    return events


async def run_template_batch(
    plan: TemplateBatchPlan,
    *,
    message: str,
    visible_tools: tuple[str, ...] | list[str],
    llm: Any = None,
    fixtures: list[dict[str, Any]] | None = None,
    fixture_version: str | int = 1,
    confirmation_provider_factory: Any | None = None,
    encoder: Any | None = None,
    should_stop: Any | None = None,
    on_run_done: Any | None = None,
) -> dict[str, Any]:
    """按已校验的模板批次计划逐运行执行;返回批次结果(逐次运行+配置快照)。

    ``llm=None``(生产路径):每次运行按各自 RunConfig 的生效参数构建
    **独立**模型客户端(温度/输出上限/并行工具调用逐运行生效);
    显式传入 llm 仅用于测试注入 Fake(共享实例不影响配置记录口径,
    applied_model_params 会如实反映实例属性)。
    ``on_run_done(record_dict)`` 在每次运行完成后回调(作业进度用)。
    """
    from bdlh_runtime.experiments.budget import JobBudget

    runs: list[dict[str, Any]] = []
    skipped: list[str] = []
    budget = JobBudget.from_env()
    for planned in plan.runs:
        if should_stop is not None and should_stop():
            skipped.append(planned.run_id)
            continue
        if budget.exhausted:
            skipped.append(planned.run_id)  # 预算终止:不再发起新调用,已完成运行保留
            continue
        provider = None
        if confirmation_provider_factory is not None:
            provider = confirmation_provider_factory(planned)
        record = await run_native_agent(
            run_config=planned.run_config,
            message=message,
            visible_tools=visible_tools,
            llm=llm,
            fixtures=fixtures,
            fixture_version=fixture_version,
            confirmation_provider=provider,
            encoder=encoder,
            run_id=planned.run_id,
            variant_label=planned.variant_label,
            repeat_index=planned.repeat_index,
            template_id=plan.template_id,
        )
        budget.record(llm_requests=record.actual_agent_steps)  # 每步至多一次逻辑模型调用
        payload = record.to_payload()
        runs.append(payload)
        if on_run_done is not None:
            with contextlib.suppress(Exception):  # 进度回调失败不影响执行
                on_run_done(payload)
    return {
        "template_id": plan.template_id,
        "template_version": plan.template_version,
        "classification": plan.classification,
        "independent_variable": list(plan.independent_variable),
        "run_count": plan.run_count,
        "fixed_conditions": plan.fixed_conditions,
        "fixed_conditions_hash": plan.fixed_conditions_hash,
        "runs": runs,
        "skipped_run_ids": skipped,
        "by_variant": _aggregate_by_variant(runs),
        "budget": budget.to_payload(),
        "budget_terminated": budget.terminated_reason or None,
    }


def _aggregate_by_variant(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in runs:
        grouped.setdefault(str(row.get("variant_label")), []).append(row)
    summary: dict[str, dict[str, Any]] = {}
    for label, rows in grouped.items():
        valid = [row for row in rows if row.get("validity") == "VALID"]
        summary[label] = {
            "total_runs": len(rows),
            "valid_runs": len(valid),
            "bypassed_event_count": sum(int(row.get("bypassed_event_count") or 0) for row in rows),
            "stop_reasons": sorted({str(row.get("stop_reason")) for row in rows}),
        }
    return summary


__all__ = [
    "CONTEXT_STRATEGY_MAP",
    "NativeRunRecord",
    "applied_params_of",
    "build_llm_for_config",
    "build_template_catalog",
    "model_param_snapshots",
    "run_native_agent",
    "run_template_batch",
    "PlannedRun",
    "ToolSearchIndex",
    "GOVERNANCE_OFF",
]
