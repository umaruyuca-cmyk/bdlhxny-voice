"""Market Data Graph：市场数据获取子图。

当前 Mock 节点只用于验证 Root Graph 的动态调度。Phase 2 接入后应替换为
MarketDataGateway，禁止 Graph 节点直接持有或调用 MCP Client。
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from stockwise_analysis.contracts.observation import DataQuality, Observation, ProvenanceRecord

from .nodes import _complete_current_task, event, now_iso
from .state import RootState


def build_market_query(state: RootState) -> dict:
    """根据 DataRequirement 形成统一能力查询计划。"""
    return {
        "events": [event(state, "market.query_planned", "build_market_query", {"mode": "mock"})]
    }


def execute_mock_market_tool(state: RootState) -> dict:
    """本地开发替身：模拟标准化行情 Observation，不访问任何外部网络。"""
    symbol = state.get("intent", {}).get("symbol") or state.get("request", {}).get("symbol") or "000000"
    provenance = ProvenanceRecord(source="mock-market", tool="market.get_realtime_quote", retrieved_at=now_iso())
    quote = Observation(
        observation_id=str(uuid4()),
        capability="market.get_realtime_quote",
        status="SUCCESS",
        data={"symbol": symbol, "price": None, "trade_date": date.today().isoformat(), "is_mock": True},
        data_quality=DataQuality(completeness=0.5, quality_status="PARTIAL"),
        provenance=[provenance],
    )
    observations = [quote.model_dump()]
    if state.get("intent", {}).get("analysis_type") in {"technical", "comprehensive", "portfolio_impact"}:
        history = Observation(
            observation_id=str(uuid4()),
            capability="market.get_historical_prices",
            status="SUCCESS",
            data=[],
            data_quality=DataQuality(completeness=0.5, quality_status="PARTIAL"),
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


def build_market_data_graph():
    """构建市场数据获取子图。"""
    graph = StateGraph(RootState)
    graph.add_node("build_market_query", build_market_query)
    graph.add_node("execute_mock_market_tool", execute_mock_market_tool)
    graph.add_node("evaluate_market_data", evaluate_market_data)
    graph.add_edge(START, "build_market_query")
    graph.add_edge("build_market_query", "execute_mock_market_tool")
    graph.add_edge("execute_mock_market_tool", "evaluate_market_data")
    graph.add_edge("evaluate_market_data", END)
    return graph.compile()
