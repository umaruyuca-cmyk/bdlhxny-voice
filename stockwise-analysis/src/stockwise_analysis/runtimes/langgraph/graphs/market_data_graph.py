"""Market Data Graph：市场数据获取子图。

两种运行模式：
- 注入 gateway_adapter + research_agent：走真实 MCP 链路，Research Agent 决策
  下一步统一能力 → Gateway 按路由表执行 → normalizer 标准化（含吞错识别）。
  循环直到所有 DataRequirement 满足或达到 ReAct 轮数上限。
- 无注入（默认）：走 mock 路径，只产出占位 Observation，保证测试不依赖网络。

ReAct 边界：Agent 只输出结构化动作（choose_next_action），不直接执行工具；
工具执行、Observation 追加、轮数控制由本子图的节点完成（架构文档 §4.3）。
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from stockwise_analysis.contracts.observation import DataQuality, Observation, ProvenanceRecord

from ..nodes.nodes import _complete_current_task, event, now_iso
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
        "events": [event(state, "market.query_planned", "build_market_query", {"requirements_count": len(state.get("data_requirements", []))})]
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
    if state.get("intent", {}).get("analysis_type") in {"technical", "comprehensive", "portfolio_impact"}:
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


def evaluate_market_data(state: RootState) -> dict:
    """完成市场数据任务；真实版本将在此检查缺失、冲突和降级结果。"""
    result = _complete_current_task(state)
    result["events"] = [event(state, "market.data_evaluated", "evaluate_market_data", {"status": "PARTIAL_MOCK"})]
    return result


def build_market_data_graph(
    gateway_adapter: Any | None = None,
    research_agent: Any | None = None,
    llm_research_agent: Any | None = None,
    max_react_rounds: int = _DEFAULT_MAX_REACT_ROUNDS,
):
    """构建市场数据获取子图（审查文档 §4.5 执行矩阵）。

    gateway_adapter / research_agent / llm_research_agent 为可选注入：
    - 都注入：走真实 MCP ReAct 循环，select_action 节点在运行时按
      analysis_type 选择 agent（comprehensive 用 LLM 版，其他用规则版）；
    - 都不传：走 mock 路径（execute_mock_market_tool），保证测试无网络依赖。

    执行矩阵（运行时由 select_action 决策）：
    - market_snapshot：确定性快路径，不启动 ReAct（直接 finish）；
    - technical/fundamental/valuation/portfolio_impact：有限自适应 ReAct
      （规则版 agent 按 DataRequirement 顺序执行）；
    - comprehensive：完整有界 ReAct（LLM 版 agent 自主决策）。
    """

    # 子图必须输出 workflow_plan：evaluate_market_data 里的 _complete_current_task
    # 会把 market_data 任务标记 COMPLETED 并随子图输出回主图。LangGraph 子图
    # 对 dict 字段按"入口快照演化"合并（最小实验已验证），因此 resolve 的
    # COMPLETED 状态会被保留，不会被覆盖回 RUNNING。
    graph = StateGraph(RootState)

    if gateway_adapter is not None and research_agent is not None:
        # ── 真实 ReAct 模式 ──
        graph.add_node("build_market_query", build_market_query)
        graph.add_node("select_action", _make_select_action_node(research_agent, llm_research_agent))
        graph.add_node("execute_tool", _make_execute_tool_node(gateway_adapter))
        graph.add_node("normalize_observation", _normalize_observations_node)
        graph.add_node("evaluate_market_data", evaluate_market_data)

        graph.add_edge(START, "build_market_query")
        graph.add_edge("build_market_query", "select_action")
        # select_action → execute_tool（有动作）或 evaluate（finish）
        graph.add_conditional_edges(
            "select_action",
            _route_after_action,
            {"execute": "execute_tool", "finish": "evaluate_market_data"},
        )
        graph.add_edge("execute_tool", "normalize_observation")
        # normalize → 回到 select_action 继续 ReAct 循环（受轮数限制）
        graph.add_conditional_edges(
            "normalize_observation",
            _make_react_router(max_react_rounds),
            {"continue": "select_action", "stop": "evaluate_market_data"},
        )
        graph.add_edge("evaluate_market_data", END)
    else:
        # ── Mock 模式（保持向后兼容）──
        graph.add_node("build_market_query", build_market_query)
        graph.add_node("execute_mock_market_tool", execute_mock_market_tool)
        graph.add_node("evaluate_market_data", evaluate_market_data)
        graph.add_edge(START, "build_market_query")
        graph.add_edge("build_market_query", "execute_mock_market_tool")
        graph.add_edge("execute_mock_market_tool", "evaluate_market_data")
        graph.add_edge("evaluate_market_data", END)

    # 子图只输出自己负责的字段（observations/events/ReAct 内部状态），
    # 不输出 workflow_plan——避免子图入口快照覆盖主图的调度进度，
    # 导致 resolve_instrument 等任务被重复执行（冒烟发现的 bug）。
    return graph.compile()


# ── 真实 ReAct 模式的节点工厂 ──


def _make_select_action_node(research_agent: Any, llm_research_agent: Any = None):
    """构建 ReAct 决策节点：按运行时 analysis_type 选择 Agent（审查文档 §4.5）。

    执行矩阵（运行时决策，不依赖构建时类型）：
    - market_snapshot：直接 finish（确定性快路径，不启动 ReAct）；
    - comprehensive 且有 LLM agent：用 LLM 版自主决策；
    - 其他：规则版按 DataRequirement 顺序（有限自适应）。
    """

    def select_action(state: RootState) -> dict:
        analysis_type = state.get("intent", {}).get("analysis_type", "market_snapshot")

        # market_snapshot 快路径：不经 ReAct，直接 finish
        if analysis_type == "market_snapshot":
            return {
                "_react_round": state.get("_react_round", 0),
                "_current_action": {"action": "finish", "arguments": {}, "reason": "快路径不启动 ReAct"},
                "events": [event(state, "model.decision", "select_action", {"action": "finish", "mode": "fast_path"})],
            }

        # 按 analysis_type 选 agent：comprehensive 用 LLM 版，其他用规则版
        agent = llm_research_agent if (analysis_type == "comprehensive" and llm_research_agent is not None) else research_agent
        observations = state.get("observations", [])
        requirements = state.get("data_requirements", [])
        action = agent.choose_next_action(observations, requirements)
        # finish 是终止决策，不计入 ReAct 轮次（轮次只统计实际工具调用），
        # 但字段必须保留（保持 state 类型稳定，避免下游 KeyError）
        if action.is_finish:
            return {
                "_react_round": state.get("_react_round", 0),
                "_current_action": action.model_dump(),
                "events": [event(state, "model.decision", "select_action", {"action": "finish"})],
            }
        round_count = state.get("_react_round", 0) + 1
        return {
            "_react_round": round_count,
            "_current_action": action.model_dump(),
            "events": [event(state, "model.decision", "select_action", {"action": action.action, "round": round_count})],
        }

    return select_action


def _route_after_action(state: RootState) -> str:
    """有动作执行，finish 则评估完成。"""
    action = state.get("_current_action", {})
    return "finish" if action.get("action") == "finish" else "execute"


def _make_execute_tool_node(gateway_adapter: Any):
    """构建工具执行节点：通过 Gateway 调用统一能力（同步工厂，返回异步节点）。"""

    async def execute_tool(state: RootState) -> dict:
        action_data = state.get("_current_action", {})
        capability = action_data.get("action", "")
        arguments = action_data.get("arguments", {})
        run_id = state.get("run_id", "")
        # Gateway 返回 Observation；网络失败由 Gateway 内部 fallback 处理
        observation = await gateway_adapter.execute(capability, arguments, run_id=run_id)
        return {
            "_pending_observation": observation.model_dump(),
            "events": [event(state, "tool.finished", "execute_tool", {"capability": capability, "status": observation.status})],
        }

    return execute_tool


def _normalize_observations_node(state: RootState) -> dict:
    """标准化刚获取的 Observation（含服务端吞错识别）。"""
    from stockwise_analysis.observations.normalizer import ObservationNormalizer

    pending = state.get("_pending_observation")
    if not pending:
        return {}
    obs = Observation.model_validate(pending)
    normalized = ObservationNormalizer().normalize(obs)
    return {
        "observations": [normalized.model_dump()],
        "events": [event(state, "observation.created", "normalize_observation", {"capability": obs.capability, "status": normalized.status})],
    }


def _make_react_router(max_rounds: int):
    """构建 ReAct 循环路由器：未达上限且需求未满足则继续，否则停止。"""

    def router(state: RootState) -> str:
        round_count = state.get("_react_round", 0)
        if round_count >= max_rounds:
            return "stop"
        # 检查是否还有未满足的需求
        observations = state.get("observations", [])
        fulfilled = {o.get("capability") for o in observations if o.get("status") == "SUCCESS"}
        requirements = state.get("data_requirements", [])
        remaining = [r for r in requirements if r.get("capability") not in fulfilled]
        return "continue" if remaining else "stop"

    return router
