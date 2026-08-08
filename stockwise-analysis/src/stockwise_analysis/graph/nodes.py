"""Root Graph 的确定性节点实现。

本文件只包含流程节点和状态转换。模型调用、MCP、Java API 与长期记忆必须
通过各自的 Adapter 注入，不能在节点内直接访问外部网络或数据库。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from langgraph.types import interrupt

from stockwise_analysis.agents.query_agent import RuleBasedQueryAgent
from stockwise_analysis.agents.summary_model import DeterministicSummaryModel
from stockwise_analysis.contracts.analysis import AnalysisInput, AnalysisResult, InstrumentRef
from stockwise_analysis.contracts.observation import DataQuality, Observation, ProvenanceRecord
from stockwise_analysis.contracts.data_requirements import DataRequirement
from stockwise_analysis.contracts.workflow import TaskSpec, WorkflowPlan

from .state import RootState


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
    """持仓上下文节点；当前 Mock，生产版本仅可通过 Java Data Adapter 查询。"""
    observation = Observation(
        observation_id=str(uuid4()),
        capability="portfolio.get_current_positions",
        status="SUCCESS",
        data={"positions": [], "account_snapshot": {"currency": "CNY"}},
        data_quality=DataQuality(completeness=1.0, quality_status="OK"),
        provenance=[ProvenanceRecord(source="mock-java", tool="portfolio.get_current_positions", retrieved_at=now_iso())],
    )
    result = _complete_current_task(state)
    result.update({"observations": [observation.model_dump()], "events": [event(state, "java_tool.completed", "load_portfolio_context", {"capability": observation.capability})]})
    return result


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
    """执行第一版 Python Analysis Engine。

    该节点严格只读取 AnalysisInput；未来替换为独立 Skill 时由
    AnalysisCapabilityAdapter 负责通信，节点接口保持不变。
    """
    analysis_input = AnalysisInput.model_validate(state.get("analysis_input", {}))
    result = AnalysisResult(
        analysis_id=analysis_input.analysis_id,
        status="SUCCESS" if analysis_input.data_quality.quality_status == "OK" else "PARTIAL",
        facts=[{"name": "instrument", "value": analysis_input.instrument.model_dump()}],
        calculated_indicators={"engine": "python-analysis.v1", "history_bars": len(analysis_input.historical_prices)},
        signals=[],
        risk_flags=[],
        conclusions=[{"text": "已完成流程骨架分析，真实 MCP 数据能力待接入。", "confidence": "LOW"}],
        limitations=["当前使用 Mock Tool，尚未接入真实 MCP 和 Java API。"],
        data_quality=analysis_input.data_quality,
        provenance=analysis_input.provenance,
    )
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
