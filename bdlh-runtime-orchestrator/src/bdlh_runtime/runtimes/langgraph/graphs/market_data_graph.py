"""Market Data Graph：市场数据获取子图。

两种运行模式：
- 注入 gateway_adapter + research_agent：走真实 MCP 链路，Research Agent 决策
  下一步统一能力 → Gateway 按路由表执行 → normalizer 标准化（含吞错识别）。
  循环直到 GoalCoverage settled（或无 Goal 时 allowed 覆盖）或触顶预算/轮次。
- 无注入（默认）：走 mock 路径，只产出占位 Observation，保证测试不依赖网络。

ReAct 边界：Agent 只输出结构化动作（choose_next_action），不直接执行工具；
工具执行、Observation 追加、轮数控制由本子图的节点完成（架构文档 §4.3）。
"""

from __future__ import annotations

from datetime import date
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from bdlh_runtime.contracts.observation import DataQuality, Observation, ProvenanceRecord
from bdlh_runtime.cognitive.goal_coverage import all_goals_settled, evaluate_goals
from bdlh_runtime.cognitive.goal_schema import GoalSpec, UnderstandOutput
from bdlh_runtime.tools.coverage import CoverageResult, evaluate_coverage

from ..nodes.nodes import _complete_current_task, current_run_observations, event, now_iso
from .state import RootState


class _MarketDataOutput(TypedDict, total=False):
    """Market Data Graph 子图的受限输出 schema。

    只包含子图负责的字段，刻意排除 workflow_plan——防止子图入口快照覆盖
    主图调度进度（resolve_instrument 等任务被重复执行的根因）。
    """

    observations: list[dict[str, Any]]
    events: list[dict[str, Any]]
    _react_round: int
    _current_action: dict[str, Any]
    _pending_observation: dict[str, Any] | None

# ReAct 轮数上限（默认值，comprehensive 可由调用方覆盖）
_DEFAULT_MAX_REACT_ROUNDS = 6


def build_market_query(state: RootState) -> dict:
    """根据 DataRequirement 形成统一能力查询计划。"""
    return {
        "events": [event(state, "market.query_planned", "build_market_query", {"allowed_count": len(state.get("allowed", []))})]
    }


def _mock_history_bars(symbol: str, count: int = 60) -> list[dict]:
    """生成确定性合成日K线（可复现的伪随机游走）。

    用固定种子的随机游走生成 OHLCV，保证：
    - 不访问网络，测试稳定；
    - 同一 symbol 永远生成同一序列（可复现）；
    - 足够长（60 根）让 MACD/RSI/ATR 都能算出来，验证 engine 真实计算。
    """

    import random

    rng = random.Random(f"mock-{symbol}")
    price = 100.0
    bars: list[dict] = []
    for i in range(count):
        drift = rng.uniform(-0.02, 0.02)
        open_ = price
        close = max(1.0, open_ * (1.0 + drift))
        high = max(open_, close) * (1.0 + rng.uniform(0, 0.01))
        low = min(open_, close) * (1.0 - rng.uniform(0, 0.01))
        bars.append({
            "date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
            "open": round(open_, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": int(rng.uniform(1e6, 5e6)),
        })
        price = close
    return bars


def execute_mock_market_tool(state: RootState) -> dict:
    """本地开发替身：模拟标准化行情 Observation，不访问任何外部网络。"""
    symbol = state.get("intent", {}).get("symbol") or state.get("request", {}).get("symbol") or "000000"
    provenance = ProvenanceRecord(source="mock-market", tool="market.get_realtime_quote", retrieved_at=now_iso())
    quote = Observation(
        observation_id=str(uuid4()),
        capability="market.get_realtime_quote",
        status="SUCCESS",
        data={"symbol": symbol, "price": 100.0, "trade_date": date.today().isoformat(), "is_mock": True},
        data_quality=DataQuality(completeness=0.5, quality_status="PARTIAL"),
        provenance=[provenance],
    )
    observations = [quote.model_dump()]
    if state.get("tool_window", {}).get("visible_capabilities") or state.get("allowed"):
        history = Observation(
            observation_id=str(uuid4()),
            capability="market.get_historical_prices",
            status="SUCCESS",
            data=_mock_history_bars(symbol),
            data_quality=DataQuality(completeness=1.0, quality_status="OK"),
            provenance=[ProvenanceRecord(source="mock-market", tool="market.get_historical_prices", retrieved_at=now_iso())],
        )
        observations.append(history.model_dump())
    return {
        "observations": observations,
        "events": [event(state, "market.tool.completed", "execute_mock_market_tool", {"symbol": symbol})],
    }


def evaluate_market_data(state: RootState, *, registry_snapshot: Any | None = None) -> dict:
    """完成市场数据任务；优先用 GoalCoverage，无 Goal 时退回 allowed 覆盖。"""
    result = _complete_current_task(state)
    observations = current_run_observations(state)
    goals_update = _refresh_goals(state, registry_snapshot, observations)
    if goals_update is not None:
        result.update(goals_update)
        coverage = _coverage_from_goals((goals_update.get("understand") or {}).get("goals") or [])
    else:
        coverage = evaluate_coverage(
            [{"capability": name, "required": False} for name in state.get("allowed", [])],
            observations,
        )
    if state.get("budget_exhausted") and coverage.status == "COMPLETE":
        coverage = coverage.model_copy(update={"status": "PARTIAL"})
    result["coverage"] = coverage.model_dump()
    result["events"] = [event(
        state,
        "market.data_evaluated",
        "evaluate_market_data",
        coverage.model_dump(),
    )]
    return result


def build_market_data_graph(
    gateway_adapter: Any | None = None,
    research_agent: Any | None = None,
    llm_research_agent: Any | None = None,
    max_react_rounds: int = _DEFAULT_MAX_REACT_ROUNDS,
    web_search_adapter: Any | None = None,
    java_adapter: Any | None = None,
    deep_research_adapter: Any | None = None,
    registry_snapshot: Any | None = None,
):
    """构建市场数据获取子图（审查文档 §4.5 执行矩阵）。

    gateway_adapter / research_agent / llm_research_agent 为可选注入：
    - 都注入：走真实 MCP ReAct 循环；单一 Agent 在窗口内选择下一步，
      白名单 = state["allowed"]（重写 §6.2：凡 needs_external 均可 Agent 选）；
    - 都不传：走 mock 路径（execute_mock_market_tool），保证测试无网络依赖。

    ``research.web_search`` → web_search_adapter；``research.deep_search`` →
    deep_research_adapter（默认关闭，ADR-016 PROPOSED）；禁止把任意 ``research.*``
    都丢进浅搜 Adapter。
    """

    # 子图必须输出 workflow_plan：evaluate_market_data 里的 _complete_current_task
    # 会把 market_data 任务标记 COMPLETED 并随子图输出回主图。LangGraph 子图
    # 对 dict 字段按"入口快照演化"合并（最小实验已验证），因此 resolve 的
    # COMPLETED 状态会被保留，不会被覆盖回 RUNNING。
    graph = StateGraph(RootState)

    if gateway_adapter is not None and research_agent is not None:
        # ── 真实 ReAct 模式 ──
        graph.add_node("build_market_query", build_market_query)
        graph.add_node(
            "select_action",
            _make_select_action_node(
                research_agent,
                llm_research_agent,
                registry_snapshot=registry_snapshot,
            ),
        )
        graph.add_node(
            "execute_tool",
            _make_execute_tool_node(
                gateway_adapter,
                web_search_adapter,
                java_adapter,
                deep_research_adapter,
            ),
        )
        graph.add_node(
            "normalize_observation",
            _make_normalize_observations_node(registry_snapshot),
        )
        graph.add_node(
            "evaluate_market_data",
            lambda state: evaluate_market_data(state, registry_snapshot=registry_snapshot),
        )

        graph.add_edge(START, "build_market_query")
        graph.add_edge("build_market_query", "select_action")
        graph.add_conditional_edges(
            "select_action",
            _route_after_action,
            {"execute": "execute_tool", "finish": "evaluate_market_data"},
        )
        graph.add_edge("execute_tool", "normalize_observation")
        graph.add_conditional_edges(
            "normalize_observation",
            _make_react_router(max_react_rounds, registry_snapshot=registry_snapshot),
            {"continue": "select_action", "stop": "evaluate_market_data"},
        )
        graph.add_edge("evaluate_market_data", END)
    else:
        # ── Mock 模式（保持向后兼容）──
        graph.add_node("build_market_query", build_market_query)
        graph.add_node("execute_mock_market_tool", execute_mock_market_tool)
        graph.add_node(
            "evaluate_market_data",
            lambda state: evaluate_market_data(state, registry_snapshot=registry_snapshot),
        )
        graph.add_edge(START, "build_market_query")
        graph.add_edge("build_market_query", "execute_mock_market_tool")
        graph.add_edge("execute_mock_market_tool", "evaluate_market_data")
        graph.add_edge("evaluate_market_data", END)

    return graph.compile()


# ── 真实 ReAct 模式的节点工厂 ──


def _make_select_action_node(
    research_agent: Any,
    llm_research_agent: Any = None,
    *,
    registry_snapshot: Any | None = None,
):
    """构建 ReAct 决策节点：候选 = 窗口 specs ⊆ allowed；Agent 唯一。"""

    from bdlh_runtime.tools.deep_research.cognitive_bridge import apply_deep_call_policy_to_action

    def select_action(state: RootState) -> dict:
        agent = llm_research_agent if llm_research_agent is not None else research_agent
        observations = current_run_observations(state)
        allowed = set(state.get("allowed", []))
        window_specs = [
            item for item in state.get("capability_candidates", [])
            if item.get("name") in allowed
        ]
        goals = _goals_from_state(state)
        refreshed = _refresh_goals(state, registry_snapshot, observations)
        if refreshed is not None:
            goals = (refreshed.get("understand") or {}).get("goals") or goals

        if not window_specs:
            payload = {
                "_react_round": state.get("_react_round", 0),
                "_current_action": {"action": "finish", "arguments": {}, "reason": "窗口无可用能力"},
                "events": [event(state, "model.decision", "select_action", {"action": "finish", "mode": "empty_window"})],
            }
            if refreshed is not None:
                payload.update(refreshed)
            return payload

        action = agent.choose_next_action(observations, window_specs, goals=goals)
        action_data = apply_deep_call_policy_to_action(
            action.model_dump(), state, allowed=allowed
        )
        if action_data.get("action") == "finish":
            payload = {
                "_react_round": state.get("_react_round", 0),
                "_current_action": action_data,
                "events": [event(state, "model.decision", "select_action", {"action": "finish"})],
            }
            if refreshed is not None:
                payload.update(refreshed)
            return payload
        round_count = state.get("_react_round", 0) + 1
        payload = {
            "_react_round": round_count,
            "_current_action": action_data,
            "events": [
                event(
                    state,
                    "model.decision",
                    "select_action",
                    {
                        "action": action_data.get("action"),
                        "round": round_count,
                        "deep_trigger_reasons": action_data.get("deep_trigger_reasons"),
                    },
                )
            ],
        }
        if refreshed is not None:
            payload.update(refreshed)
        return payload

    return select_action


def _route_after_action(state: RootState) -> str:
    """有动作执行，finish 则评估完成。"""
    action = state.get("_current_action", {})
    return "finish" if action.get("action") == "finish" else "execute"


def _fill_action_arguments(action_data: dict, state: RootState) -> dict:
    """执行前回填参数占位（规则版 Agent 产生 {arg: None}）。

    symbol 类参数从 understand.entities.instruments 取当前标的；
    web_search 的 query 以标的兜底；deep_search 拼 DeepResearchRequest 契约字段。
    """
    from bdlh_runtime.tools.deep_research.cognitive_bridge import build_deep_research_arguments

    arguments = dict(action_data.get("arguments") or {})
    capability = str(action_data.get("action") or "")
    if capability == "research.deep_search":
        return build_deep_research_arguments(state, base=arguments)

    if not any(value is None for value in arguments.values()):
        return arguments
    instruments = (state.get("understand", {}).get("entities") or {}).get("instruments") or []
    symbol = instruments[0] if instruments else state.get("request", {}).get("symbol")
    for key, value in arguments.items():
        if value is not None:
            continue
        if key == "symbol" and symbol is not None:
            arguments[key] = symbol
        elif key == "query" and symbol is not None:
            arguments[key] = f"{symbol} 最新动态"
        elif key == "lookback_days":
            arguments[key] = 120
    return arguments


def _budget_limit(state: RootState, name: str) -> int | None:
    budget = state.get("budget") or {}
    value = budget.get(name)
    return int(value) if value is not None else None


def _budget_exceeded_observation(capability: str) -> Observation:
    return Observation(
        observation_id=str(uuid4()),
        capability=capability,
        status="FAILED",
        data=None,
        data_quality=DataQuality(quality_status="INVALID", known_unavailable=[capability]),
        error_code="BUDGET_EXCEEDED",
        error_message="analysis budget does not allow another tool call",
    )


def _quote_arguments(state: RootState) -> dict[str, Any]:
    instruments = (state.get("understand", {}).get("entities") or {}).get("instruments") or []
    symbol = (instruments[0] if instruments else None) or state.get("request", {}).get("symbol")
    return {"symbol": symbol} if symbol else {}


def _make_execute_tool_node(
    gateway_adapter: Any,
    web_search_adapter: Any | None = None,
    java_adapter: Any | None = None,
    deep_research_adapter: Any | None = None,
):
    """构建工具执行节点：按能力精确路由到对应 adapter（同步工厂，返回异步节点）。

    能力路由（架构文档 §13 + ADR-016）：
    - research.web_search → web_search_adapter（SearXNG 浅搜）
    - research.deep_search → deep_research_adapter（复合研究；未注入则 UNAVAILABLE）
    - portfolio.* / user.* → java_adapter
    - 其他（market.* 等） → gateway_adapter（MCP）
    禁止 ``research.*`` 前缀整段丢进浅搜 Adapter（避免 deep 静默串味）。
    """

    async def execute_tool(state: RootState) -> dict:
        action_data = state.get("_current_action", {})
        capability = action_data.get("action", "")
        arguments = _fill_action_arguments(action_data, state)
        run_id = state.get("run_id", "")
        used = state.get("tool_calls_used", 0)
        allowed = set(state.get("allowed", []))
        if capability not in allowed:
            observation = Observation(
                observation_id=str(uuid4()),
                capability=capability or "unknown",
                status="FAILED",
                data=None,
                data_quality=DataQuality(quality_status="INVALID"),
                error_code="CAPABILITY_NOT_ALLOWED",
                error_message="research action is outside the per-turn capability whitelist",
            )
            return {
                "_pending_observation": observation.model_dump(),
                "events": [event(state, "tool.blocked", "execute_tool", {"capability": capability, "reason": "not_allowed"})],
            }
        limit = _budget_limit(state, "tool_call_limit")
        if limit is not None and used >= limit:
            observation = _budget_exceeded_observation(capability)
            return {
                "_pending_observation": observation.model_dump(),
                "budget_exhausted": True,
                "events": [event(state, "tool.blocked", "execute_tool", {"capability": capability, "reason": "budget_exceeded"})],
            }
        if capability == "research.web_search":
            if web_search_adapter is None:
                observation = Observation(
                    observation_id=str(uuid4()),
                    capability=capability,
                    status="UNAVAILABLE",
                    data=None,
                    data_quality=DataQuality(
                        quality_status="INVALID",
                        known_unavailable=[capability],
                    ),
                    error_code="WEB_SEARCH_ADAPTER_MISSING",
                    error_message="research.web_search adapter is not configured",
                )
            else:
                observation = await web_search_adapter.execute(capability, arguments)
        elif capability == "research.deep_search":
            if deep_research_adapter is None:
                observation = Observation(
                    observation_id=str(uuid4()),
                    capability=capability,
                    status="UNAVAILABLE",
                    data=None,
                    data_quality=DataQuality(
                        quality_status="INVALID",
                        known_unavailable=[capability],
                    ),
                    error_code="DEEP_RESEARCH_NOT_ENABLED",
                    error_message=(
                        "research.deep_search is not wired or Flag is off (ADR-016); "
                        "ordinary queries must use research.web_search"
                    ),
                )
            else:
                observation = await deep_research_adapter.execute(capability, arguments)
                observation = _apply_research_data_guardrail(observation, state)
        elif capability.startswith("research."):
            observation = Observation(
                observation_id=str(uuid4()),
                capability=capability,
                status="FAILED",
                data=None,
                data_quality=DataQuality(quality_status="INVALID"),
                error_code="UNKNOWN_RESEARCH_CAPABILITY",
                error_message=f"unsupported research capability: {capability}",
            )
        elif (capability.startswith("portfolio.") or capability.startswith("user.")) and java_adapter is not None:
            observation = await java_adapter.execute(capability, arguments)
        else:
            observation = await gateway_adapter.execute(capability, arguments, run_id=run_id)
        return {
            "_pending_observation": observation.model_dump(),
            "tool_calls_used": used + 1,
            "events": [event(state, "tool.finished", "execute_tool", {"capability": capability, "status": observation.status})],
        }

    return execute_tool


def _apply_research_data_guardrail(observation: Observation, state: RootState) -> Observation:
    """Result 时点：对可用的 deep_search Observation 跑 Data-quality 研究规则。

    已是 FAILED/UNAVAILABLE 的观测不再二次改写，避免掩盖执行器原始错误码。
    """
    if observation.status in {"FAILED", "UNAVAILABLE"}:
        return observation

    from bdlh_runtime.guardrails import DefaultDataQualityGuardrail, GuardrailContext, GuardrailDecision

    context = GuardrailContext(
        run_id=str(state.get("run_id") or "unknown"),
        authenticated_user_id=str(
            (state.get("request") or {}).get("user_id")
            or (state.get("auth") or {}).get("user_id")
            or "anonymous"
        ),
        authorized_capabilities=frozenset(state.get("allowed") or []),
    )
    result = DefaultDataQualityGuardrail().evaluate_data_quality(observation, context=context)
    if result.decision == GuardrailDecision.ALLOW:
        return observation
    return observation.model_copy(
        update={
            "status": "FAILED",
            "error_code": result.audit_code or "DATA_QUALITY_BLOCKED",
            "error_message": "; ".join(result.reasons) or "research data quality blocked",
        }
    )


def _normalize_observations_node(state: RootState) -> dict:
    """兼容旧调用：无快照时只做 Observation 标准化。"""
    return _make_normalize_observations_node(None)(state)


def _make_normalize_observations_node(registry_snapshot: Any | None):
    """标准化 Observation，并按 GoalCoverage 回写 goals 状态。"""

    def normalize_observation(state: RootState) -> dict:
        from bdlh_runtime.observations.normalizer import ObservationNormalizer

        pending = state.get("_pending_observation")
        if not pending:
            return {}
        obs = Observation.model_validate(pending)
        normalized = ObservationNormalizer().normalize(obs)
        payload: dict[str, Any] = {
            "observations": [normalized.model_dump()],
            "events": [
                event(
                    state,
                    "observation.created",
                    "normalize_observation",
                    {"capability": obs.capability, "status": normalized.status},
                )
            ],
        }
        observations = current_run_observations(state) + [normalized.model_dump()]
        refreshed = _refresh_goals(state, registry_snapshot, observations)
        if refreshed is not None:
            payload.update(refreshed)
        return payload

    return normalize_observation


def _make_react_router(max_rounds: int, *, registry_snapshot: Any | None = None):
    """ReAct 循环路由：Goal settled / 预算 / 轮次触顶则停，禁止扫完整个 allowed。"""

    def router(state: RootState) -> str:
        if state.get("budget_exhausted"):
            return "stop"
        round_count = state.get("_react_round", 0)
        configured_limit = _budget_limit(state, "react_round_limit")
        if round_count >= (configured_limit if configured_limit is not None else max_rounds):
            return "stop"

        observations = current_run_observations(state)
        refreshed = _refresh_goals(state, registry_snapshot, observations)
        goals = (
            ((refreshed or {}).get("understand") or {}).get("goals")
            or _goals_from_state(state)
        )
        if goals:
            try:
                specs = [GoalSpec.model_validate(item) for item in goals]
            except Exception:  # noqa: BLE001
                specs = []
            if specs and all_goals_settled(specs):
                return "stop"
            # 仍有 PENDING：若候选都已尝试则停，避免空转
            pending_names = {
                name
                for goal in goals
                if str(goal.get("status") or "PENDING") == "PENDING"
                for criterion in (goal.get("success_criteria") or [])
                for name in (criterion.get("candidate_capabilities") or [])
            }
            attempted = {
                o.get("capability") for o in observations if o.get("capability")
            }
            remaining = [name for name in pending_names if name not in attempted]
            return "continue" if remaining else "stop"

        # 无 Goal：退回旧语义（未尝试的 allowed）
        attempted = {o.get("capability") for o in observations if o.get("capability")}
        remaining = [name for name in state.get("allowed", []) if name not in attempted]
        return "continue" if remaining else "stop"

    return router


def _goals_from_state(state: RootState) -> list[dict[str, Any]]:
    understand = state.get("understand") or {}
    goals = understand.get("goals") or []
    return list(goals) if isinstance(goals, list) else []


def _refresh_goals(
    state: RootState,
    registry_snapshot: Any | None,
    observations: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if registry_snapshot is None:
        return None
    raw = state.get("understand")
    if not raw:
        return None
    try:
        understand = UnderstandOutput.model_validate(raw)
    except Exception:  # noqa: BLE001
        return None
    allowed = list(state.get("allowed") or [])
    updated = evaluate_goals(
        understand.goals,
        observations,
        allowed,
        registry_snapshot,
    )
    return {
        "understand": understand.model_copy(update={"goals": updated}).model_dump(),
    }


def _coverage_from_goals(goals: list[dict[str, Any]]) -> CoverageResult:
    statuses = [str(goal.get("status") or "PENDING") for goal in goals]
    if not statuses:
        return CoverageResult(status="LIMITED", missing_required=["goals"])
    if all(status in {"COVERED", "BLOCKED"} for status in statuses):
        if any(status == "COVERED" for status in statuses):
            return CoverageResult(
                status="COMPLETE" if all(status == "COVERED" for status in statuses) else "PARTIAL",
                fulfilled=[g.get("goal_id", "") for g in goals if g.get("status") == "COVERED"],
                missing_optional=[g.get("goal_id", "") for g in goals if g.get("status") == "BLOCKED"],
            )
        return CoverageResult(
            status="LIMITED",
            missing_required=[g.get("goal_id", "") for g in goals],
        )
    return CoverageResult(
        status="PARTIAL",
        fulfilled=[g.get("goal_id", "") for g in goals if g.get("status") == "COVERED"],
        missing_required=[g.get("goal_id", "") for g in goals if g.get("status") == "PENDING"],
        missing_optional=[g.get("goal_id", "") for g in goals if g.get("status") == "BLOCKED"],
    )
