"""Root Graph 的确定性节点实现。

本文件只包含流程节点和状态转换。模型调用、MCP、Java API 与长期记忆必须
通过各自的 Adapter 注入，不能在节点内直接访问外部网络或数据库。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from langgraph.types import interrupt

from stockwise_analysis.runtimes.langgraph.agents.query_agent import RuleBasedQueryAgent
from stockwise_analysis.runtimes.langgraph.agents.summary_model import DeterministicSummaryModel
from stockwise_analysis.contracts.analysis import AnalysisInput, AnalysisResult, InstrumentRef
from stockwise_analysis.contracts.observation import DataQuality, Observation, ProvenanceRecord
from stockwise_analysis.contracts.data_requirements import DataRequirement
from stockwise_analysis.contracts.workflow import TaskSpec, WorkflowPlan

from ..graphs.state import RootState


def now_iso() -> str:
    """生成统一 UTC 时间戳，供事件和溯源记录使用。"""
    return datetime.now(timezone.utc).isoformat()


def event(state: RootState, event_type: str, node: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """创建可通过 SSE 输出的结构化运行事件。"""
    return {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "node": node,
        "run_id": state.get("run_id", "unknown"),
        "timestamp": now_iso(),
        "payload": payload or {},
    }


def receive_request(state: RootState) -> dict[str, Any]:
    """规范化 API 输入并标记一次新的 Graph 运行开始。"""
    request = state.get("request") or {}
    if isinstance(request, str):
        request = {"message": request}
    request = {"message": "", **request}
    return {
        "request": request,
        "status": "RUNNING",
        "events": [event(state, "run.started", "receive_request", {"request": request})],
    }


def understand_request(state: RootState) -> dict[str, Any]:
    """解析当前请求的最小意图。

    当前规则实现仅用于 Phase 0/1 骨架验证；生产版本应委托 Query Agent 输出
    受 Pydantic 契约约束的意图，而不是继续扩展关键词判断。
    """
    # Graph 节点只依赖 Agent 输出契约；当前使用确定性替身，后续替换为 LLM。
    intent = RuleBasedQueryAgent().understand(state.get("request", {})).model_dump()
    return {
        "intent": intent,
        "confirmation_required": intent["requires_confirmation"],
        "events": [event(state, "query.understood", "understand_request", intent)],
    }


def check_missing_context(state: RootState) -> dict[str, Any]:
    """检查是否缺少执行数据计划所必需的标的或分析范围。"""
    intent = state.get("intent", {})
    missing = []
    if not intent.get("symbol"):
        missing.append("symbol")
    if not intent.get("analysis_type"):
        missing.append("analysis_type")
    return {
        "needs_clarification": bool(missing),
        "clarification_request": {"reason": "missing_context", "required_fields": missing} if missing else None,
        "events": [event(state, "query.context_checked", "check_missing_context", {"missing": missing})],
    }


def interrupt_for_clarification(state: RootState) -> dict[str, Any]:
    """通过 LangGraph interrupt() 暂停，等待用户补充信息后原线程恢复。"""
    answer = interrupt(
        {
            "reason": "missing_context",
            "required_fields": state.get("clarification_request", {}).get("required_fields", []),
            "message": "请补充分析标的和必要的分析范围。",
        }
    )
    answer = answer if isinstance(answer, dict) else {"message": str(answer)}
    request = {**state.get("request", {}), **answer}
    return {
        "request": request,
        "needs_clarification": False,
        "events": [event(state, "user.clarification_received", "interrupt_for_clarification", answer)],
    }


def build_data_requirements(state: RootState) -> dict[str, Any]:
    """由意图生成统一数据能力需求和可执行 WorkflowPlan。"""
    intent = state.get("intent", {})
    analysis_type = intent.get("analysis_type", "market_snapshot")
    symbol = intent.get("symbol") or state.get("request", {}).get("symbol")
    requirements = [
        DataRequirement(requirement_id="instrument", capability="market.resolve_instrument", required=True, reason="确认分析标的", arguments={"symbol": symbol}),
        DataRequirement(requirement_id="market", capability="market.get_realtime_quote", required=True, reason="获取当前市场数据", arguments={"symbol": symbol}),
    ]
    if analysis_type in {"technical", "comprehensive", "portfolio_impact"}:
        requirements.append(
            DataRequirement(requirement_id="history", capability="market.get_historical_prices", required=True, reason="技术分析需要历史价格", arguments={"symbol": symbol, "lookback_days": 120})
        )
    if analysis_type in {"fundamental", "valuation", "comprehensive"}:
        requirements.append(
            DataRequirement(requirement_id="financial", capability="market.get_financial_statements", required=analysis_type != "valuation", reason="基本面分析需要财务数据", arguments={"symbol": symbol})
        )
    if analysis_type in {"valuation", "comprehensive"}:
        requirements.append(
            DataRequirement(requirement_id="valuation", capability="market.get_valuation", required=True, reason="估值分析需要估值数据", arguments={"symbol": symbol})
        )
    if intent.get("requires_portfolio"):
        requirements.append(
            DataRequirement(requirement_id="portfolio", capability="portfolio.get_current_positions", required=True, reason="持仓影响分析需要用户持仓", arguments={"user_id": state.get("user_id")})
        )
    return {
        "data_requirements": [item.model_dump() for item in requirements],
        "workflow_plan": _plan_for(state, analysis_type, bool(intent.get("requires_portfolio"))),
        "events": [event(state, "workflow.planned", "build_data_requirements", {"analysis_type": analysis_type})],
    }


def _plan_for(state: RootState, analysis_type: str, requires_portfolio: bool) -> dict[str, Any]:
    """构建任务依赖图；调度器据此选择下一个可执行节点。"""
    tasks = [
        TaskSpec(task_id="resolve_instrument", task_type="resolve_instrument", output_ref=["instrument"]),
        TaskSpec(task_id="market_data", task_type="market_data", depends_on=["resolve_instrument"], output_ref=["observations"]),
    ]
    if requires_portfolio:
        tasks.append(TaskSpec(task_id="portfolio_context", task_type="portfolio_context", depends_on=["market_data"], output_ref=["portfolio_context"]))
    tasks.extend(
        [
            TaskSpec(task_id="assemble_analysis", task_type="assemble_analysis", depends_on=[tasks[-1].task_id], output_ref=["analysis_input"]),
            TaskSpec(task_id="analysis", task_type="analysis", depends_on=["assemble_analysis"], output_ref=["analysis_result"]),
            TaskSpec(task_id="validate_analysis", task_type="validate_analysis", depends_on=["analysis"], output_ref=["analysis_result"]),
            TaskSpec(task_id="compose_response", task_type="compose_response", depends_on=["validate_analysis"], output_ref=["final_response"]),
        ]
    )
    if state.get("request", {}).get("require_confirmation"):
        tasks.append(TaskSpec(task_id="user_confirmation", task_type="user_confirmation", depends_on=["compose_response"], output_ref=["confirmation"]))
    return WorkflowPlan(plan_id=str(uuid4()), analysis_type=analysis_type, tasks=tasks).model_dump()


def dispatch_workflow(state: RootState) -> dict[str, Any]:
    """选择依赖已经完成的任务，并写入下一跳路由键。"""
    plan = WorkflowPlan.model_validate(state.get("workflow_plan", {}))
    task = plan.next_pending()
    if task is None:
        return {"next_stage": "finish", "events": [event(state, "workflow.ready_to_finish", "dispatch_workflow")]}
    plan = plan.mark(task.task_id, "RUNNING")
    return {
        "workflow_plan": plan.model_dump(),
        "current_task_id": task.task_id,
        "next_stage": task.task_type,
        "events": [event(state, "workflow.task_started", "dispatch_workflow", {"task_id": task.task_id, "task_type": task.task_type})],
    }


def _complete_current_task(state: RootState) -> dict[str, Any]:
    """将当前任务标记完成；所有任务完成后才允许结束流程。"""
    plan = WorkflowPlan.model_validate(state.get("workflow_plan", {}))
    task_id = state.get("current_task_id")
    return {"workflow_plan": plan.mark(task_id, "COMPLETED").model_dump()} if task_id else {}


def resolve_instrument(state: RootState) -> dict[str, Any]:
    """标的解析节点；Phase 2 将替换为 market.resolve_instrument Gateway 调用。"""
    intent = state.get("intent", {})
    symbol = intent.get("symbol") or state.get("request", {}).get("symbol")
    instrument = InstrumentRef(symbol=str(symbol), name=f"标的 {symbol}")
    observation = Observation(
        observation_id=str(uuid4()),
        capability="market.resolve_instrument",
        status="SUCCESS",
        data=instrument.model_dump(),
        data_quality=DataQuality(completeness=1.0, freshness="REALTIME", quality_status="OK"),
        provenance=[ProvenanceRecord(source="mock", tool="resolve_instrument", retrieved_at=now_iso())],
    )
    result = _complete_current_task(state)
    result.update({"observations": [observation.model_dump()], "events": [event(state, "tool.completed", "resolve_instrument", {"capability": observation.capability})]})
    return result


def load_portfolio_context(state: RootState) -> dict[str, Any]:
    """持仓上下文节点（无注入时的默认实现）。

    当前为 Mock 兜底（空持仓），保证无 Java 服务时流程可跑通。生产环境由
    Application Runtime 注入 JavaDataAdapter 的工厂节点替代（见下方工厂）。
    """
    observation = Observation(
        observation_id=str(uuid4()),
        capability="portfolio.get_current_positions",
        status="SUCCESS",
        data={"positions": [], "account_snapshot": {"currency": "CNY"}, "is_mock": True},
        data_quality=DataQuality(completeness=1.0, quality_status="OK"),
        provenance=[ProvenanceRecord(source="mock-java", tool="portfolio.get_current_positions", retrieved_at=now_iso())],
    )
    result = _complete_current_task(state)
    result.update({"observations": [observation.model_dump()], "events": [event(state, "java_tool.completed", "load_portfolio_context", {"capability": observation.capability})]})
    return result


def make_load_portfolio_context_node(java_adapter: Any):
    """构建持仓上下文节点（工厂函数，注入 JavaDataAdapter）。

    有注入时通过 Java Adapter 获取真实持仓（Adapter 内部自带 mock 降级）；
    无注入时走默认 mock 节点。节点产出统一 Observation（capability=
    portfolio.get_current_positions），assemble_analysis 按此提取。
    """

    async def load_portfolio_with_adapter(state: RootState) -> dict[str, Any]:
        capability = "portfolio.get_current_positions"
        observation = await java_adapter.execute(
            capability,
            {"user_id": state.get("user_id")},
        )
        result = _complete_current_task(state)
        result.update({
            "observations": [observation.model_dump()],
            "events": [event(state, "java_tool.completed", "load_portfolio_context", {"capability": capability, "status": observation.status})],
        })
        return result

    return load_portfolio_with_adapter


def assemble_analysis(state: RootState) -> dict[str, Any]:
    """将标准化 Observation 组装为纯分析契约 AnalysisInput。"""
    observations = [Observation.model_validate(item) for item in state.get("observations", [])]
    instrument_data = next((item.data for item in observations if item.capability == "market.resolve_instrument"), {})
    quote = next((item.data for item in observations if item.capability == "market.get_realtime_quote"), None)
    history = next((item.data for item in observations if item.capability == "market.get_historical_prices"), [])
    portfolio = next((item.data for item in observations if item.capability == "portfolio.get_current_positions"), None)
    provenance = [record for item in observations for record in item.provenance]
    quality_ok = all(item.status == "SUCCESS" and item.data_quality.quality_status == "OK" for item in observations)
    quality = DataQuality(
        completeness=sum(item.data_quality.completeness for item in observations) / max(len(observations), 1),
        freshness="REALTIME",
        quality_status="OK" if quality_ok else "PARTIAL",
    )
    analysis_input = AnalysisInput(
        analysis_id=state.get("run_id", str(uuid4())),
        analysis_type=state.get("intent", {}).get("analysis_type", "market_snapshot"),
        instrument=InstrumentRef.model_validate(instrument_data),
        realtime_quote=quote,
        historical_prices=history,
        portfolio_context=portfolio,
        data_quality=quality,
        provenance=provenance,
    )
    result = _complete_current_task(state)
    result.update({"analysis_input": analysis_input.model_dump(), "events": [event(state, "analysis.input_assembled", "assemble_analysis")]})
    return result


def run_analysis(state: RootState) -> dict[str, Any]:
    """执行 Python Analysis Engine。

    节点只读取 AnalysisInput，委托 domain/analysis_engine.analyze 完成确定性
    计算（技术指标/风险/信号），不在这里实现任何计算逻辑。未来替换为独立
    Skill 时由 AnalysisCapabilityAdapter 负责通信，节点接口保持不变。
    """
    from stockwise_analysis.domain.analysis_engine import analyze

    analysis_input = AnalysisInput.model_validate(state.get("analysis_input", {}))
    result = analyze(analysis_input)
    complete = _complete_current_task(state)
    complete.update({"analysis_result": result.model_dump(), "events": [event(state, "analysis.completed", "run_analysis", {"status": result.status})]})
    return complete


def validate_analysis(state: RootState) -> dict[str, Any]:
    """校验 AnalysisResult 的最小契约并传播分析状态。"""
    result = AnalysisResult.model_validate(state.get("analysis_result", {}))
    complete = _complete_current_task(state)
    complete.update({"status": result.status, "events": [event(state, "analysis.validated", "validate_analysis", {"status": result.status})]})
    return complete


def compose_response(state: RootState) -> dict[str, Any]:
    """构建暂定响应；Phase 3 将由 Summary Model 输出用户可读解释。"""
    result = AnalysisResult.model_validate(state.get("analysis_result", {}))
    response = DeterministicSummaryModel().compose(result)
    complete = _complete_current_task(state)
    complete.update({"final_response": response, "events": [event(state, "response.composed", "compose_response")]})
    return complete


def confirm_user(state: RootState) -> dict[str, Any]:
    """需要人工确认时暂停；确认后的记忆写入将在独立节点处理。"""
    confirmation = interrupt({"reason": "user_confirmation", "response": state.get("final_response"), "message": "是否确认保存本次分析结果？"})
    complete = _complete_current_task(state)
    complete.update({"confirmation": confirmation, "events": [event(state, "user.confirmed", "confirm_user", {"confirmation": confirmation})]})
    return complete


def finish(state: RootState) -> dict[str, Any]:
    """写入结束事件，交由 Checkpointer 保存最终状态。"""
    return {"status": state.get("status", "SUCCESS"), "next_stage": None, "events": [event(state, "run.finished", "finish")]}


# ── 记忆层节点（首尾读写，ReAct 循环不碰）──
# 这些节点通过工厂函数注入 MemoryStore 实例，保持"节点不直接持有外部依赖"
# 的原则。Mem0 不可用时注入的是 NoOpMemoryStore，行为降级为无记忆。


def make_load_memory_node(memory_store: Any):
    """构建对话首部的记忆召回节点（工厂函数）。

    返回一个 async 节点函数。在 Root Graph 入口处执行一次：读取用户画像 +
    语义召回相关记忆，写入 state 供 ContextBuilder 第 ②⑤ 块使用。
    Mem0 失败时降级返回空（MemoryStore 接口保证），主流程继续。
    """

    async def load_memory(state: RootState) -> dict[str, Any]:
        user_id = state.get("user_id")
        events: list[dict[str, Any]] = []
        profile = None
        recalled: list[dict[str, Any]] = []
        if user_id:
            try:
                profile = await memory_store.get_profile(user_id)
                query = str(state.get("request", {}).get("message", ""))
                if query:
                    records = await memory_store.search(query, user_id, limit=5)
                    recalled = [
                        {"content": r.content, "score": r.score, "metadata": r.metadata}
                        for r in records
                    ]
                events.append(event(state, "memory.read", "load_memory", {"profile_hit": profile is not None, "recall_count": len(recalled)}))
            except Exception as exc:
                # 二次兜底：MemoryStore 实现本应自行降级，这里再保一层
                events.append(event(state, "memory.read_failed", "load_memory", {"error": str(exc)[:120]}))
        else:
            events.append(event(state, "memory.skipped", "load_memory", {"reason": "no user_id"}))
        return {
            "user_profile": profile.__dict__ if profile else None,
            "recalled_memories": recalled,
            "events": events,
        }

    return load_memory


def make_persist_memory_node(memory_store: Any):
    """构建对话尾部的记忆沉淀节点（工厂函数）。

    返回一个 async 节点函数。在 Root Graph 结束前执行一次，写入两类记忆：
    1. 本轮对话摘要（用户问 + 分析结论），常规沉淀；
    2. 用户确认后的研究结论（Phase 4 知识入库）：若 confirm_user 已确认，
       结论以 knowledge_type=confirmed 标记写入，供后续对话作为可信知识召回。

    Mem0 失败时仅记日志不阻塞（MemoryStore.add 保证），记忆是增强项不是
    关键路径（见架构文档 v3.1 §5.4）。
    """

    async def persist_memory(state: RootState) -> dict[str, Any]:
        user_id = state.get("user_id")
        events: list[dict[str, Any]] = []
        if user_id:
            # ── 1. 常规沉淀：用户问题 + 分析结论摘要 ──
            message = str(state.get("request", {}).get("message", ""))
            result = state.get("analysis_result", {})
            conclusions = result.get("conclusions", []) if isinstance(result, dict) else []
            summary_parts = [f"用户问：{message}"] if message else []
            for c in conclusions[:3]:
                summary_parts.append(f"结论：{c.get('text', c) if isinstance(c, dict) else c}")
            content = " | ".join(summary_parts)
            if content:
                try:
                    await memory_store.add(content, user_id, metadata={"run_id": state.get("run_id")})
                    events.append(event(state, "memory.written", "persist_memory", {"content_len": len(content)}))
                except Exception as exc:
                    events.append(event(state, "memory.write_failed", "persist_memory", {"error": str(exc)[:120]}))

            # ── 2. 用户确认后的知识入库（Phase 4）──
            confirmation = state.get("confirmation")
            confirmed = confirmation is not None and not _is_negative_confirmation(confirmation)
            if confirmed and conclusions:
                knowledge = " | ".join(
                    f"已确认结论：{c.get('text', c) if isinstance(c, dict) else c}"
                    for c in conclusions[:5]
                )
                try:
                    await memory_store.add(
                        knowledge,
                        user_id,
                        metadata={
                            "run_id": state.get("run_id"),
                            "knowledge_type": "confirmed",  # 标记为已确认知识
                            "symbol": state.get("intent", {}).get("symbol"),
                        },
                    )
                    events.append(event(state, "memory.knowledge_saved", "persist_memory", {"knowledge_type": "confirmed"}))
                except Exception as exc:
                    events.append(event(state, "memory.knowledge_save_failed", "persist_memory", {"error": str(exc)[:120]}))

        events.append(event(state, "run.persisted", "persist_memory"))
        return {"events": events}

    return persist_memory


def _is_negative_confirmation(confirmation: Any) -> bool:
    """判断用户确认是否为拒绝。

    兼容两种形态：dict（{"confirmed": false} 或 {"answer": "否"}）
    和字符串（"否"/"不要"/"不保存"等）。
    """

    if isinstance(confirmation, dict):
        if confirmation.get("confirmed") is False:
            return True
        answer = str(confirmation.get("answer", confirmation.get("message", ""))).strip()
    else:
        answer = str(confirmation).strip()
    return any(word in answer for word in ("否", "不要", "不保存", "拒绝", "不用"))


# ── ContextBuilder 感知的节点工厂 ──
# 旧版 understand_request / compose_response 硬编码规则替身，这里提供工厂版本，
# 让 Application Runtime 注入 LLM 版 Agent 和 ContextBuilder。无注入时降级回规则版。


def make_understand_request_node(query_agent: Any):
    """构建带 ContextBuilder 的理解节点（工厂函数）。

    注入的 query_agent 可以是 RuleBasedQueryAgent（无 LLM）或 LlmQueryAgent
    （有 LLM）。节点内部组装上下文后委托 agent.understand 输出意图。
    """

    def understand_with_context(state: RootState) -> dict[str, Any]:
        intent = query_agent.understand(state.get("request", {})).model_dump()
        return {
            "intent": intent,
            "confirmation_required": intent["requires_confirmation"],
            "events": [event(state, "query.understood", "understand_request", intent)],
        }

    return understand_with_context


def make_compose_response_node(summary_model: Any):
    """构建带 SummaryModel 的响应节点（工厂函数）。

    注入的 summary_model 可以是 DeterministicSummaryModel（无 LLM）或
    LlmSummaryModel（有 LLM）。节点内部委托 model.compose 生成最终响应。
    """

    def compose_with_model(state: RootState) -> dict[str, Any]:
        result = AnalysisResult.model_validate(state.get("analysis_result", {}))
        response = summary_model.compose(result)
        complete = _complete_current_task(state)
        complete.update({"final_response": response, "events": [event(state, "response.composed", "compose_response")]})
        return complete

    return compose_with_model
