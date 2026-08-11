"""Root Graph 的确定性节点实现。

本文件只包含流程节点和状态转换。模型调用、MCP、Java API 与长期记忆必须
通过各自的 Adapter 注入，不能在节点内直接访问外部网络或数据库。
"""

from __future__ import annotations

from dataclasses import asdict
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
from stockwise_analysis.runtime.budgets import budget_for

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
    """规范化 API 输入并标记一次新的 Graph 运行开始。

    同时把用户消息写入 conversation（v2.1 §7：短期记忆累积），供 ContextBuilder
    截断和跨轮上下文使用。
    """
    request = state.get("request") or {}
    if isinstance(request, str):
        request = {"message": request}
    request = {"message": "", **request}
    return {
        "request": request,
        "status": "RUNNING",
        "conversation": [{"role": "user", "content": request.get("message", ""), "run_id": state.get("run_id", "")}],
        "events": [event(state, "run.started", "receive_request", {"request": request})],
    }


def _enrich_intent_with_context(state: RootState, intent: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """跨轮标的继承（v2.1 §7.3）：缺 symbol 时从会话实体表找最近标的继承。

    返回 (enriched_intent, entities_addition)。entities_addition 含本轮解析出的标的，
    供写入 state.entities 供后续轮次继承。
    """
    entities_addition: list[dict[str, Any]] = []
    symbol = intent.get("symbol")
    if not symbol:
        # 从会话实体表找最近的 instrument 标的继承
        for ent in reversed(state.get("entities", [])):
            if ent.get("entity_type") == "instrument" and ent.get("symbol"):
                symbol = ent["symbol"]
                intent["symbol"] = symbol
                intent["_symbol_inherited"] = True  # 标记本次标的来自跨轮继承
                break
    # 本轮有标的则写入实体表，供后续轮次继承
    if symbol:
        entities_addition.append({
            "entity_id": str(uuid4()),
            "entity_type": "instrument",
            "symbol": symbol,
            "raw_text": str(state.get("request", {}).get("message", "")),
            "resolution_status": "resolved",
            "source_run_id": state.get("run_id", ""),
        })
    return intent, entities_addition


def understand_request(state: RootState) -> dict[str, Any]:
    """解析当前请求的最小意图，并做跨轮标的继承（v2.1 §7.3）。

    当前规则实现用于骨架验证；生产版本应委托 Query Agent 输出受 Pydantic 契约
    约束的意图。缺 symbol 时从会话实体表继承前文标的。
    """
    intent = RuleBasedQueryAgent().understand(state.get("request", {})).model_dump()
    intent, entities_addition = _enrich_intent_with_context(state, intent)
    return {
        "intent": intent,
        "entities": entities_addition,
        "confirmation_required": intent["requires_confirmation"],
        "events": [event(state, "query.understood", "understand_request", intent)],
    }


def check_missing_context(state: RootState) -> dict[str, Any]:
    """检查是否存在无法合理默认且会明显改变答案的关键信息（v2.1 §8）。

    不再因缺少 symbol 强制中断——宏观/行业/知识问答等问题不需要股票代码。
    只在"确实需要标的且无法合理默认"时才补问。
    """
    intent = state.get("intent", {})
    analysis_type = intent.get("analysis_type", "market_snapshot")
    missing: list[str] = []

    # 知识问答/市场整体/综合/宏观类不需要 symbol，不补问。
    # 单股分析类（technical/fundamental/valuation/portfolio_impact）确实需要标的。
    needs_symbol = analysis_type in {"technical", "fundamental", "valuation", "portfolio_impact"}
    if needs_symbol and not intent.get("symbol"):
        missing.append("symbol")

    return {
        "needs_clarification": bool(missing),
        "clarification_request": {"reason": "missing_context", "required_fields": missing} if missing else None,
        "events": [event(state, "query.context_checked", "check_missing_context", {"missing": missing})],
    }


def route_execution(state: RootState) -> dict[str, Any]:
    """执行模式选择（v2.1 §3）：direct_response / single_capability / agent_loop。

    规则版降级（无 LLM）：基于 QueryIntent 判断。生产可注入 LLM 版（本阶段先规则版）。
    - 知识问答（含"什么是/解释/定义"等）→ direct_response，不调工具；
    - 有 symbol 且 market_snapshot → single_capability（一次 quote）；
    - 其他（含名称需解析、复杂研究）→ agent_loop；拿不准偏向 agent_loop。
    """
    from stockwise_analysis.contracts.route import IntentRoute, ToolProposal

    intent = state.get("intent", {})
    analysis_type = intent.get("analysis_type", "market_snapshot")
    symbol = intent.get("symbol")
    message = str(state.get("request", {}).get("message", ""))

    # 知识问答关键词 → direct_response（不依赖实时金融事实）
    knowledge_keywords = ("什么是", "解释", "定义", "含义", "什么意思", "怎么理解", "是指")
    if any(kw in message for kw in knowledge_keywords):
        route = IntentRoute(mode="direct_response", reason="知识问答，无需工具", confidence=0.8)
        return {"intent_route": route.model_dump(), "events": [event(state, "intent.routed", "route_execution", {"mode": "direct_response"})]}

    # 有 symbol 且单点查询 → single_capability（v2.1 §3.4：已解析 symbol 才走单能力）
    if symbol and analysis_type == "market_snapshot":
        route = IntentRoute(
            mode="single_capability",
            reason="单点数据查询，标的已解析",
            confidence=0.8,
            tool_proposal=ToolProposal(capability="market.get_realtime_quote", arguments={"symbol": symbol}),
        )
        return {"intent_route": route.model_dump(), "events": [event(state, "intent.routed", "route_execution", {"mode": "single_capability"})]}

    # 其他 → agent_loop（含名称需解析、复杂研究；拿不准偏向 agent_loop）
    route = IntentRoute(mode="agent_loop", reason="复杂研究或名称需解析，走 planner", confidence=0.6)
    return {"intent_route": route.model_dump(), "events": [event(state, "intent.routed", "route_execution", {"mode": "agent_loop"})]}


def direct_response_node(state: RootState) -> dict[str, Any]:
    """direct_response 快路径（v2.1 §3）：不调工具/不分析，直接生成回答。

    基于 intent_route.direct_answer 或简单模板生成 final_response。
    生产环境应由 LLM 生成；当前规则版用模板兜底。
    发现需要实时数据时由调用方升级到 agent_loop（记录 upgrade 事件）。
    """
    route_data = state.get("intent_route", {})
    direct_answer = route_data.get("direct_answer")
    message = str(state.get("request", {}).get("message", ""))

    if not direct_answer:
        direct_answer = f"关于「{message}」：这是一个金融知识问题。当前规则版未接入 LLM 直接回答能力，生产环境应由 LLM 生成解释。"

    response = {
        "analysis_id": state.get("run_id", ""),
        "answer": direct_answer,
        "mode": "direct_response",
        "limitations": ["规则版直接回答，未接入 LLM；生产环境应由 LLM 生成"],
    }
    return {
        "final_response": response,
        "status": "SUCCESS",
        "conversation": [{"role": "assistant", "content": response, "run_id": state.get("run_id", "")}],
        "events": [event(state, "response.completed", "direct_response_node", {"mode": "direct_response"})],
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
    # 注意：data_requirements 只含"市场数据能力"（由 Market Data Graph 的
    # ReAct 处理）。resolve_instrument 和 portfolio 由独立节点执行（resolve_
    # instrument / load_portfolio_context），若列入 requirements 会导致
    # ReAct 循环重复执行它们（审查冒烟发现的 bug）。
    requirements = [
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
    # comprehensive 补充网络搜索（市场/板块/宏观背景，非关键，缺失不阻断）
    if analysis_type == "comprehensive":
        symbol_or_topic = symbol or state.get("intent", {}).get("scope") or "A股市场"
        requirements.append(
            DataRequirement(
                requirement_id="web_search",
                capability="research.web_search",
                required=False,
                reason="综合分析需要市场最新动态和新闻舆情",
                arguments={"query": f"{symbol_or_topic} 最新动态", "mode": "NEWS", "max_results": 5},
            )
        )
    # portfolio 由独立节点 load_portfolio_context 处理，不列入 ReAct requirements
    return {
        "data_requirements": [item.model_dump() for item in requirements],
        "budget": asdict(budget_for(analysis_type)),
        "tool_calls_used": 0,
        "budget_exhausted": False,
        "workflow_plan": _plan_for(state, analysis_type, bool(intent.get("requires_portfolio"))),
        "events": [event(state, "workflow.planned", "build_data_requirements", {"analysis_type": analysis_type, "budget": asdict(budget_for(analysis_type))})],
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
    """标的解析节点（无 gateway 注入时的 Mock 兜底）。

    生产环境由 Application Runtime 注入 Gateway 版本（见下方工厂），
    标的解析必须经由 MarketDataGateway 而非在节点内拼接（审查文档 §4.6）。
    """
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


def make_resolve_instrument_node(gateway_adapter: Any):
    """构建标的解析节点（工厂函数，审查文档 §4.6）。

    有 gateway 注入时：标的解析经由 MarketDataGateway 执行
    market.resolve_instrument，返回结果经 normalizer 标准化后写入
    observations。解析失败时触发 interrupt 请求补充或返回结构化失败，
    不允许在节点中拼接"标的名称"。
    """
    from stockwise_analysis.observations.normalizer import ObservationNormalizer

    async def resolve_with_gateway(state: RootState) -> dict[str, Any]:
        intent = state.get("intent", {})
        symbol = intent.get("symbol") or state.get("request", {}).get("symbol")
        if not symbol:
            # 无标的 → 触发中断请求补充
            answer = interrupt({"reason": "missing_symbol", "message": "请提供要分析的股票代码。"})
            symbol = str(answer.get("symbol", answer)) if isinstance(answer, dict) else str(answer)

        raw_obs = await gateway_adapter.execute(
            "market.resolve_instrument",
            {"symbol": symbol},
            run_id=state.get("run_id", ""),
        )
        normalized = ObservationNormalizer().normalize(raw_obs)
        result = _complete_current_task(state)
        result.update({
            "observations": [normalized.model_dump()],
            "events": [event(state, "tool.completed", "resolve_instrument", {"capability": "market.resolve_instrument", "status": normalized.status})],
        })
        return result

    return resolve_with_gateway


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
    """将标准化 Observation 组装为纯分析契约 AnalysisInput（审查文档 §4.7）。

    按 capability 映射全部数据域到 AnalysisInput 对应字段：
    financial_data / valuation_data / industry_context / news_context /
    overseas_context 全部装配，不再只装行情和历史。
    缺失字段写入 data_quality.known_unavailable 和 limitations（如实标记，
    不伪造成功数据）。
    """
    observations = [Observation.model_validate(item) for item in state.get("observations", [])]

    # capability → AnalysisInput 字段的映射
    _CAPABILITY_TO_FIELD = {
        "market.resolve_instrument": "instrument",
        "market.get_realtime_quote": "realtime_quote",
        "market.get_historical_prices": "historical_prices",
        "market.get_financial_statements": "financial_data",
        "market.get_valuation": "valuation_data",
        "market.get_industry_context": "industry_context",
        "market.get_news": "news_context",
        "portfolio.get_current_positions": "portfolio_context",
        "market.get_overseas": "overseas_context",  # 预留：MCP 暂不覆盖外围面
    }

    assembled: dict[str, Any] = {}
    known_unavailable: list[str] = []
    provenance: list[Any] = []

    for obs in observations:
        field = _CAPABILITY_TO_FIELD.get(obs.capability)
        if field is None:
            continue
        provenance.extend(obs.provenance)
        if obs.status == "SUCCESS" and obs.data is not None:
            if field == "historical_prices":
                assembled[field] = obs.data if isinstance(obs.data, list) else []
            elif field == "news_context":
                # news 解析为 {"items": [...]}，提取列表
                assembled[field] = obs.data.get("items", []) if isinstance(obs.data, dict) else []
            elif field == "instrument":
                assembled[field] = obs.data
            else:
                assembled[field] = obs.data
        else:
            # 失败/缺失的数据域如实标记
            known_unavailable.append(obs.capability)

    # 默认值：必须存在的字段
    instrument_data = assembled.get("instrument") or {"symbol": (state.get("intent", {}).get("symbol") or "unknown")}

    # 数据质量：completeness 按"本分析类型实际请求的 DataRequirement 中已满足
    # 的比例"计算，而非全局域数——market_snapshot 只需 quote，不应因财报缺失
    # 被扣分。缺失进 known_unavailable。
    required_capabilities = {req.get("capability") for req in state.get("data_requirements", [])}
    fulfilled = {obs.capability for obs in observations if obs.status == "SUCCESS" and obs.capability in _CAPABILITY_TO_FIELD}
    if required_capabilities:
        completeness = len(required_capabilities & fulfilled) / len(required_capabilities)
    else:
        completeness = len(fulfilled) / max(len(_CAPABILITY_TO_FIELD), 1)
    quality_status = "OK" if completeness >= 1.0 else ("PARTIAL" if completeness >= 0.5 else "INVALID")
    quality = DataQuality(
        completeness=round(completeness, 2),
        freshness="REALTIME",
        quality_status=quality_status,
        known_unavailable=known_unavailable,
    )

    analysis_input = AnalysisInput(
        analysis_id=state.get("run_id", str(uuid4())),
        analysis_type=state.get("intent", {}).get("analysis_type", "market_snapshot"),
        instrument=InstrumentRef.model_validate(instrument_data),
        realtime_quote=assembled.get("realtime_quote"),
        historical_prices=assembled.get("historical_prices", []),
        financial_data=assembled.get("financial_data"),
        valuation_data=assembled.get("valuation_data"),
        industry_context=assembled.get("industry_context"),
        news_context=assembled.get("news_context", []),
        portfolio_context=assembled.get("portfolio_context"),
        overseas_context=assembled.get("overseas_context"),
        data_quality=quality,
        provenance=provenance,
    )
    result = _complete_current_task(state)
    result.update({
        "analysis_input": analysis_input.model_dump(),
        "events": [event(state, "analysis.input_assembled", "assemble_analysis", {"known_unavailable": known_unavailable})],
    })
    return result


def _run_analysis_with_adapter(state: RootState, analysis_capability: Any) -> dict[str, Any]:
    """执行 Python Analysis Engine。

    节点只读取 AnalysisInput，委托 domain/analysis_engine.analyze 完成确定性
    计算（技术指标/风险/信号），不在这里实现任何计算逻辑。未来替换为独立
    Skill 时由 AnalysisCapabilityAdapter 负责通信，节点接口保持不变。
    """
    analysis_input = AnalysisInput.model_validate(state.get("analysis_input", {}))
    result = analysis_capability.analyze(analysis_input)
    complete = _complete_current_task(state)
    complete.update({"analysis_result": result.model_dump(), "events": [event(state, "analysis.completed", "run_analysis", {"status": result.status})]})
    return complete


def make_run_analysis_node(analysis_capability: Any):
    """创建分析能力节点，隔离 Graph 与 Python/远程分析实现。"""

    def run_analysis_with_adapter(state: RootState) -> dict[str, Any]:
        return _run_analysis_with_adapter(state, analysis_capability)

    return run_analysis_with_adapter


def run_analysis(state: RootState) -> dict[str, Any]:
    """兼容旧调用的默认分析节点；生产 Graph 应通过 Adapter 注入实现。"""
    from stockwise_analysis.tools.analysis_capability import PythonAnalysisCapabilityAdapter

    return _run_analysis_with_adapter(state, PythonAnalysisCapabilityAdapter())


def validate_analysis(state: RootState) -> dict[str, Any]:
    """校验 AnalysisResult 的最小契约并传播分析状态。"""
    result = AnalysisResult.model_validate(state.get("analysis_result", {}))
    complete = _complete_current_task(state)
    complete.update({"status": result.status, "events": [event(state, "analysis.validated", "validate_analysis", {"status": result.status})]})
    return complete


def compose_response(state: RootState) -> dict[str, Any]:
    """构建暂定响应，并写入 conversation（v2.1 §7 短期记忆累积）。"""
    result = AnalysisResult.model_validate(state.get("analysis_result", {}))
    response = DeterministicSummaryModel().compose(result)
    complete = _complete_current_task(state)
    complete.update({
        "final_response": response,
        "conversation": [{"role": "assistant", "content": response, "run_id": state.get("run_id", "")}],
        "events": [event(state, "response.composed", "compose_response")],
    })
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
            # v2.1 §9.2：不自动写临时摘要（用户问+结论），只写用户确认后的稳定知识。
            # 临时行情、未确认推断、一次性结论不得自动写入 Mem0。
            confirmation = state.get("confirmation")
            confirmed = confirmation is not None and not _is_negative_confirmation(confirmation)
            result = state.get("analysis_result", {})
            conclusions = result.get("conclusions", []) if isinstance(result, dict) else []
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


def make_persist_history_node(history_store: Any):
    """构建分析历史写入节点（v2.1 §9.3）。

    在 finish 后执行一次，把本次运行的关键快照写入历史存储（审计 + 历史查询）。
    失败仅记事件不阻塞主流程。与 Mem0 长期记忆分离：History 记录运行事实，
    Mem0 记录用户偏好。
    """
    from stockwise_analysis.contracts.history import AnalysisHistoryRecord

    async def persist_history(state: RootState) -> dict[str, Any]:
        try:
            record = AnalysisHistoryRecord(
                history_id=str(uuid4()),
                thread_id=state.get("thread_id", state.get("run_id", "")),
                run_id=state.get("run_id", ""),
                authenticated_user_id=state.get("user_id"),
                request_snapshot=state.get("request", {}),
                intent_snapshot=state.get("intent", {}),
                observations_summary=[
                    {"capability": o.get("capability"), "status": o.get("status")}
                    for o in state.get("observations", [])
                ],
                analysis_result=state.get("analysis_result"),
                status=state.get("status", "RUNNING"),
            )
            history_store.save(record)
            return {"events": [event(state, "history.saved", "persist_history", {"history_id": record.history_id})]}
        except Exception as exc:
            return {"events": [event(state, "history.save_failed", "persist_history", {"error": str(exc)[:120]})]}

    return persist_history


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


def make_understand_request_node(query_agent: Any, context_builder: Any = None):
    """构建带 ContextBuilder 的理解节点（工厂函数）。

    注入的 query_agent 可以是 RuleBasedQueryAgent（无 LLM）或 LlmQueryAgent
    （有 LLM）。context_builder 可选注入：组装七块上下文（画像/记忆/本轮数据）
    传给 agent，让 LLM 理解时能感知用户画像和历史记忆（审查文档 §4.4）。
    无注入时行为不变。
    """

    def understand_with_context(state: RootState) -> dict[str, Any]:
        request = state.get("request", {})
        extra_context: dict[str, Any] | None = None
        if context_builder is not None:
            ctx = context_builder.build(
                user_profile=state.get("user_profile"),
                conversation=state.get("conversation", []),
                recalled_memories=state.get("recalled_memories", []),
                round_data=state.get("observations", []),
                user_input=request,
            )
            # 只把语义/确定性块传给 agent（避免把工具清单等冗余塞给意图识别）
            extra_context = {
                "user_profile": ctx.blocks["user_profile"].content if "user_profile" in ctx.blocks else {},
                "recalled_memories": ctx.blocks["recalled_memories"].content if "recalled_memories" in ctx.blocks else [],
            }

        # LlmQueryAgent 支持 extra_context 参数；规则版忽略它
        try:
            intent = query_agent.understand(request, extra_context=extra_context).model_dump()
        except TypeError:
            intent = query_agent.understand(request).model_dump()
        intent, entities_addition = _enrich_intent_with_context(state, intent)
        return {
            "intent": intent,
            "entities": entities_addition,
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
        complete.update({
            "final_response": response,
            "conversation": [{"role": "assistant", "content": response, "run_id": state.get("run_id", "")}],
            "events": [event(state, "response.composed", "compose_response")],
        })
        return complete

    return compose_with_model
