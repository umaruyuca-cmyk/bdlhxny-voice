"""LangGraph 顶层业务流程。

Root Graph 是唯一的业务编排入口。节点可以是普通代码、子图或未来的 Agent，
但工具执行、预算、恢复和结束判断始终由外层流程控制。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

try:
    from langgraph.checkpoint.memory import InMemorySaver
except ImportError:  # LangGraph versions before the rename expose MemorySaver.
    from langgraph.checkpoint.memory import MemorySaver as InMemorySaver

from .nodes import (
    assemble_analysis,
    compose_response,
    confirm_user,
    dispatch_workflow,
    finish,
    load_portfolio_context,
    resolve_instrument,
    run_analysis,
    validate_analysis,
)
from .query_graph import build_query_graph
from .state import RootState
from .market_data_graph import build_market_data_graph


def route_stage(state: RootState) -> str:
    """根据动态 WorkflowPlan 给出的下一阶段进行条件路由。"""

    return state.get("next_stage") or "finish"


def build_root_graph(checkpointer=None):
    """构建顶层动态流程。

    开发环境使用 InMemorySaver 方便测试；生产环境必须从 Runtime 注入
    PostgreSQL 或 Redis Checkpointer，Graph 拓扑和节点代码不随之改变。
    """

    graph = StateGraph(RootState)
    graph.add_node("query_graph", build_query_graph())
    graph.add_node("dispatch_workflow", dispatch_workflow)
    graph.add_node("resolve_instrument", resolve_instrument)
    graph.add_node("market_data_graph", build_market_data_graph())
    graph.add_node("load_portfolio_context", load_portfolio_context)
    graph.add_node("assemble_analysis", assemble_analysis)
    graph.add_node("run_analysis", run_analysis)
    graph.add_node("validate_analysis", validate_analysis)
    graph.add_node("compose_response", compose_response)
    graph.add_node("confirm_user", confirm_user)
    graph.add_node("finish", finish)

    graph.add_edge(START, "query_graph")
    graph.add_edge("query_graph", "dispatch_workflow")
    graph.add_conditional_edges(
        "dispatch_workflow",
        route_stage,
        {
            "resolve_instrument": "resolve_instrument",
            "market_data": "market_data_graph",
            "portfolio_context": "load_portfolio_context",
            "assemble_analysis": "assemble_analysis",
            "analysis": "run_analysis",
            "validate_analysis": "validate_analysis",
            "compose_response": "compose_response",
            "user_confirmation": "confirm_user",
            "finish": "finish",
        },
    )
    # 每个业务任务完成后回到统一调度节点，继续执行下一个可满足依赖的任务。
    for node in (
        "resolve_instrument",
        "market_data_graph",
        "load_portfolio_context",
        "assemble_analysis",
        "run_analysis",
        "validate_analysis",
        "compose_response",
        "confirm_user",
    ):
        graph.add_edge(node, "dispatch_workflow")
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer or InMemorySaver())


def initial_state(run_id: str, request: dict[str, Any], user_id: str | None = None) -> RootState:
    """初始化一次运行所需的最小 State，避免 API 层直接拼装内部字段。"""
    return {
        "run_id": run_id,
        "thread_id": run_id,
        "user_id": user_id,
        "request": request,
        "conversation": [],
        "observations": [],
        "errors": [],
        "events": [],
        "status": "RUNNING",
        "confirmation_required": bool(request.get("require_confirmation", False)),
    }
