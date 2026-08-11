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

from ..nodes.nodes import (
    assemble_analysis,
    compose_response,
    confirm_user,
    dispatch_workflow,
    finish,
    load_portfolio_context,
    make_compose_response_node,
    make_load_memory_node,
    make_load_portfolio_context_node,
    make_persist_memory_node,
    make_run_analysis_node,
    make_resolve_instrument_node,
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


def build_root_graph(
    checkpointer=None,
    memory_store=None,
    query_agent=None,
    summary_model=None,
    gateway_adapter=None,
    research_agent=None,
    llm_research_agent=None,
    java_adapter=None,
    context_builder=None,
    analysis_capability=None,
):
    """构建顶层动态流程。

    所有可选注入参数遵循同一原则：有注入走增强版（LLM/记忆/MCP/Java），无注入
    走规则版降级，保证 Graph 在任何环境都能跑。Application Runtime 负责装配。

    - checkpointer：状态持久化，默认 InMemorySaver。
    - memory_store：有则在首尾插入 load/persist 记忆节点（Mem0）。
    - query_agent：有则 query_graph 用 LLM 版理解节点。
    - summary_model：有则 compose_response 用 LLM 版总结。
    - gateway_adapter + research_agent：有则 market_data_graph 走真实 MCP ReAct。
    - java_adapter：有则 load_portfolio_context 走真实 Java 服务（内部自带 mock 降级）。
    - context_builder：有则理解节点用七块上下文（审查文档 §4.4）。
    """

    graph = StateGraph(RootState)

    # 记忆首部节点：有 memory_store 时才加入（工厂函数闭包绑定实例）
    has_memory = memory_store is not None
    if has_memory:
        graph.add_node("load_memory", make_load_memory_node(memory_store))

    graph.add_node("query_graph", build_query_graph(query_agent=query_agent, context_builder=context_builder))
    graph.add_node("dispatch_workflow", dispatch_workflow)
    # 有 gateway 时标的解析走真实 Gateway（审查文档 §4.6），否则 mock
    resolve_node = make_resolve_instrument_node(gateway_adapter) if gateway_adapter is not None else resolve_instrument
    graph.add_node("resolve_instrument", resolve_node)
    # research_agent（规则版）+ llm_research_agent（comprehensive 用，审查 §4.5）
    graph.add_node(
        "market_data_graph",
        build_market_data_graph(
            gateway_adapter=gateway_adapter,
            research_agent=research_agent,
            llm_research_agent=llm_research_agent,
        ),
    )
    # 有 java_adapter 用工厂节点（真实 Java + 内部降级），否则用默认 mock
    portfolio_node = make_load_portfolio_context_node(java_adapter) if java_adapter is not None else load_portfolio_context
    graph.add_node("load_portfolio_context", portfolio_node)
    graph.add_node("assemble_analysis", assemble_analysis)
    analysis_node = make_run_analysis_node(analysis_capability) if analysis_capability is not None else run_analysis
    graph.add_node("run_analysis", analysis_node)
    graph.add_node("validate_analysis", validate_analysis)
    # 有 summary_model 用工厂版，否则用原版 compose_response
    compose_node = make_compose_response_node(summary_model) if summary_model is not None else compose_response
    graph.add_node("compose_response", compose_node)
    graph.add_node("confirm_user", confirm_user)

    # 记忆尾部节点
    if has_memory:
        graph.add_node("persist_memory", make_persist_memory_node(memory_store))

    graph.add_node("finish", finish)

    # 入口：有记忆时先 load_memory 再 query_graph，否则直接 query_graph
    if has_memory:
        graph.add_edge(START, "load_memory")
        graph.add_edge("load_memory", "query_graph")
    else:
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

    # 出口：有记忆时 finish 之前先 persist_memory
    if has_memory:
        graph.add_edge("finish", "persist_memory")
        graph.add_edge("persist_memory", END)
    else:
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
