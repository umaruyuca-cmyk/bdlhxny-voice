"""Root Graph 的确定性节点实现。

本文件只包含流程节点和状态转换。模型调用、MCP、Java API 与长期记忆必须
通过各自的 Adapter 注入，不能在节点内直接访问外部网络或数据库。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from langgraph.types import interrupt

from bdlh_runtime.runtimes.langgraph.agents.query_agent import RuleBasedUnderstandAgent
from bdlh_runtime.runtimes.langgraph.agents.summary_model import DeterministicSummaryModel
from bdlh_runtime.cognitive.goal_coverage import backfill_criteria
from bdlh_runtime.cognitive.goal_schema import UnderstandOutput
from bdlh_runtime.contracts.analysis import AnalysisInput, AnalysisResult, InstrumentRef
from bdlh_runtime.contracts.observation import DataQuality, Observation, ProvenanceRecord
from bdlh_runtime.contracts.workflow import TaskSpec, WorkflowPlan
from bdlh_runtime.registry import (
    RegistrySnapshot,
    allowed_capabilities,
    apply_feature_gates,
    build_window,
    effective_operations,
    eligible_capabilities,
)
from bdlh_runtime.runtime.budgets import budget_for_profile, budget_state

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
        "_observation_start_index": len(state.get("observations", [])),
        "conversation": [{"role": "user", "content": request.get("message", ""), "run_id": state.get("run_id", "")}],
        "events": [event(state, "run.started", "receive_request", {"request": request})],
    }


def current_run_observations(state: RootState) -> list[dict[str, Any]]:
    """只返回本次运行产生的 Observation，排除同线程历史轮次数据。"""

    observations = state.get("observations", [])
    start = int(state.get("_observation_start_index", 0) or 0)
    return observations[start:]


def _enrich_understand_with_context(
    state: RootState, output: UnderstandOutput
) -> tuple[UnderstandOutput, list[dict[str, Any]]]:
    """跨轮标的继承：缺 instruments 时从会话实体表找最近标的继承。"""
    entities_addition: list[dict[str, Any]] = []
    instruments = list(output.entities.instruments)
    if not instruments:
        for ent in reversed(state.get("entities", [])):
            if ent.get("entity_type") == "instrument" and ent.get("symbol"):
                instruments = [ent["symbol"]]
                break
    for symbol in instruments:
        entities_addition.append({
            "entity_id": str(uuid4()),
            "entity_type": "instrument",
            "symbol": symbol,
            "raw_text": str(state.get("request", {}).get("message", "")),
            "resolution_status": "resolved",
            "source_run_id": state.get("run_id", ""),
        })
    if instruments != list(output.entities.instruments):
        # 继承补到标的后，清除因缺标的产生的 missing（补问已无必要）
        missing = [item for item in output.missing if item != "symbol"] if instruments else output.missing
        output = output.model_copy(
            update={
                "entities": output.entities.model_copy(update={"instruments": instruments}),
                "missing": missing,
            }
        )
    return output, entities_addition


def understand_request(state: RootState) -> dict[str, Any]:
    """理解节点（重写 §2）：goals[] 立案，不做工具选择。"""
    output = RuleBasedUnderstandAgent().understand(state.get("request", {}))
    output, entities_addition = _enrich_understand_with_context(state, output)
    return {
        "understand": output.model_dump(),
        "entities": entities_addition,
        "events": [event(state, "query.understood", "understand_request", {"goals": [g.goal_id for g in output.goals]})],
    }


def check_missing_context(state: RootState) -> dict[str, Any]:
    """检查理解节点给出的缺口（UnderstandOutput.missing），不做类型推断。"""
    understand = state.get("understand", {})
    missing = list(understand.get("missing", []))
    return {
        "needs_clarification": bool(missing),
        "clarification_request": {"reason": "missing_context", "required_fields": missing} if missing else None,
        "events": [event(state, "query.context_checked", "check_missing_context", {"missing": missing})],
    }


def direct_response_node(state: RootState) -> dict[str, Any]:
    """direct_response 快路径（v2.1 §3）：不调工具/不分析，直接生成回答。

    无工具回答（重写 §2）：仅服务快路径已结束或 needs_external=false 的情况；
    生产环境由直接回答模型生成，规则版用模板兜底。
    """
    message = str(state.get("request", {}).get("message", ""))
    direct_answer = f"关于「{message}」：这是一个知识性问题，当前装配未注入直接回答模型。"

    response = {
        "analysis_id": state.get("run_id", ""),
        "answer": direct_answer,
        "mode": "no_tool_response",
        "limitations": ["规则版直接回答，未接入 LLM；生产环境应由 LLM 生成解释"],
    }
    return {
        "final_response": response,
        "status": "SUCCESS",
        "conversation": [{"role": "assistant", "content": response, "run_id": state.get("run_id", "")}],
        "events": [event(state, "response.completed", "direct_response_node", {"mode": "no_tool_response"})],
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
    clarification_text = str(answer.get("message") or answer.get("symbol") or "").strip()
    return {
        "request": request,
        "needs_clarification": False,
        "conversation": ([{
            "role": "user",
            "content": clarification_text,
            "run_id": state.get("run_id", ""),
        }] if clarification_text else []),
        "events": [event(state, "user.clarification_received", "interrupt_for_clarification", answer)],
    }


def make_direct_response_node(direct_response_model: Any):
    """创建一次直接模型调用节点；该节点不是 ReAct，不具备工具访问能力。"""

    def answer_without_tools(state: RootState) -> dict[str, Any]:
        message = str(state.get("request", {}).get("message", "")).strip()
        answer = direct_response_model.answer(message)
        response = {
            "analysis_id": state.get("run_id", ""),
            "answer": answer,
            "mode": "direct_response",
            "limitations": [],
        }
        return {
            "final_response": response,
            "status": "SUCCESS",
            "conversation": [{
                "role": "assistant",
                "content": response,
                "run_id": state.get("run_id", ""),
            }],
            "events": [event(
                state,
                "response.completed",
                "direct_response_node",
                {"mode": "direct_llm", "uses_tools": False},
            )],
        }

    return answer_without_tools


def make_build_allowed_menu_node(
    snapshot: RegistrySnapshot,
    *,
    deep_research_enabled: bool = False,
):
    """菜单节点（重写 §5）：资格交集 → eligible → allowed → 窗口。

    菜单由资格决定（不读 goals / 不读用户原句）；goals 只参与窗口排序。
    ``research.deep_search`` 另受 Feature Flag 门控（ADR-016 §17.4）。
    """
    budget_record = budget_for_profile(snapshot, "default")

    def build_allowed_menu(state: RootState) -> dict[str, Any]:
        ops = effective_operations(snapshot, account_id="*")
        eligible = eligible_capabilities(snapshot, ops)
        authenticated = state.get("user_id") is not None
        allowed = allowed_capabilities(eligible, authenticated=authenticated)
        allowed = apply_feature_gates(
            allowed, deep_research_enabled=deep_research_enabled
        )
        allowed_names = [cap.name for cap in allowed]
        window = build_window(snapshot, allowed)

        understand = UnderstandOutput.model_validate(state.get("understand", {}))
        goals = backfill_criteria(snapshot, understand.goals, allowed_names)
        understand = understand.model_copy(
            update={"goals": goals}
        ).model_dump()

        return {
            "understand": understand,
            "eligible": [cap.name for cap in eligible],
            "allowed": allowed_names,
            "tool_window": {
                "allowed_hash": window.allowed_hash,
                "visible_toolsets": window.visible_toolsets,
                "visible_capabilities": window.visible_capabilities,
                "expansion_reason": window.expansion_reason,
                "generation": window.generation,
            },
            "capability_candidates": [cap.manifest() for cap in allowed],
            "budget": budget_state(budget_record),
            "tool_calls_used": 0,
            "budget_exhausted": False,
            "workflow_plan": _plan_for(
                state,
                requires_portfolio=any(goal.needs_account for goal in goals),
            ),
            "events": [event(state, "menu.built", "build_allowed_menu", {
                "eligible": len(eligible),
                "allowed": len(allowed_names),
                "authenticated": authenticated,
            })],
        }

    return build_allowed_menu


def _plan_for(state: RootState, requires_portfolio: bool) -> dict[str, Any]:
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
    return WorkflowPlan(plan_id=str(uuid4()), tasks=tasks).model_dump()


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
    understand = state.get("understand", {})
    instruments = (understand.get("entities") or {}).get("instruments") or []
    symbol = (instruments[0] if instruments else None) or state.get("request", {}).get("symbol")
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
    from bdlh_runtime.observations.normalizer import ObservationNormalizer

    async def resolve_with_gateway(state: RootState) -> dict[str, Any]:
        understand = state.get("understand", {})
        instruments = (understand.get("entities") or {}).get("instruments") or []
        symbol = (instruments[0] if instruments else None) or state.get("request", {}).get("symbol")
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
    from bdlh_runtime.runtimes.shared import assemble_analysis_input

    observations = [Observation.model_validate(item) for item in current_run_observations(state)]
    understand = state.get("understand", {})
    instruments = (understand.get("entities") or {}).get("instruments") or []
    analysis_input = assemble_analysis_input(
        analysis_id=state.get("run_id", str(uuid4())),
        symbol=instruments[0] if instruments else "unknown",
        observations=observations,
        requested_capabilities=state.get("allowed", []),
    )
    result = _complete_current_task(state)
    result.update({
        "analysis_input": analysis_input.model_dump(),
        "events": [event(
            state,
            "analysis.input_assembled",
            "assemble_analysis",
            {"known_unavailable": analysis_input.data_quality.known_unavailable},
        )],
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
    from bdlh_runtime.tools.analysis_capability import PythonAnalysisCapabilityAdapter

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
                            "symbol": ((state.get("understand", {}).get("entities") or {}).get("instruments") or [None])[0],
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
    from bdlh_runtime.contracts.history import AnalysisHistoryRecord

    async def persist_history(state: RootState) -> dict[str, Any]:
        try:
            record = AnalysisHistoryRecord(
                history_id=str(uuid4()),
                thread_id=state.get("thread_id", state.get("run_id", "")),
                run_id=state.get("run_id", ""),
                authenticated_user_id=state.get("user_id"),
                request_snapshot=state.get("request", {}),
                intent_snapshot=state.get("understand", {}),
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

    async def understand_with_context(state: RootState) -> dict[str, Any]:
        request = state.get("request", {})
        extra_context: dict[str, Any] | None = None
        if context_builder is not None:
            if getattr(context_builder, "is_context_service", False):
                ctx = await context_builder.build(
                    user_id=state.get("user_id"),
                    conversation=state.get("conversation", []),
                    round_data=state.get("observations", []),
                    user_input=request,
                    purpose="classify",
                    budget="small",
                )
            else:
                ctx = context_builder.build(
                    user_profile=state.get("user_profile"),
                    conversation=state.get("conversation", []),
                    recalled_memories=state.get("recalled_memories", []),
                    round_data=state.get("observations", []),
                    user_input=request,
                    purpose="classify",
                    budget="small",
                )
            # 只把语义/确定性块传给 agent（避免把工具清单等冗余塞给意图识别）
            extra_context = {
                "user_profile": ctx.blocks["user_profile"].content if "user_profile" in ctx.blocks else {},
                "recalled_memories": ctx.blocks["recalled_memories"].content if "recalled_memories" in ctx.blocks else [],
            }

        # LlmUnderstandAgent 支持 extra_context 参数；规则版忽略它
        try:
            output = query_agent.understand(request, extra_context=extra_context)
        except TypeError:
            output = query_agent.understand(request)
        output, entities_addition = _enrich_understand_with_context(state, output)
        return {
            "understand": output.model_dump(),
            "entities": entities_addition,
            "events": [event(state, "query.understood", "understand_request", {"goals": [g.goal_id for g in output.goals]})],
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
