"""Query Graph：负责理解问题、补充上下文并生成动态数据需求。"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..nodes.nodes import (
    build_data_requirements,
    check_missing_context,
    make_understand_request_node,
    understand_request,
    interrupt_for_clarification,
    receive_request,
)
from .state import RootState


def route_after_context(state: RootState) -> str:
    """缺少关键信息时暂停；完整时才允许进入数据规划。"""
    return "clarify" if state.get("needs_clarification") else "plan"


def build_query_graph(query_agent=None, context_builder=None):
    """构建问题理解子图。

    query_agent 为可选注入：传入 QueryAgent 实例时，understand_request 节点
    使用 LLM 版（或注入的规则版）；不传时用默认 RuleBasedQueryAgent。
    context_builder 为可选注入：组装七块上下文传给 agent（审查文档 §4.4）。
    无论哪种，interrupt 和计划契约不变。
    """

    graph = StateGraph(RootState)
    # 有注入 agent 时用工厂版节点（闭包绑定 agent），否则用原版
    understand_node = (
        make_understand_request_node(query_agent, context_builder)
        if query_agent is not None
        else understand_request
    )

    graph.add_node("receive_request", receive_request)
    graph.add_node("understand_request", understand_node)
    graph.add_node("check_missing_context", check_missing_context)
    graph.add_node("interrupt_for_clarification", interrupt_for_clarification)
    graph.add_node("build_data_requirements", build_data_requirements)

    graph.add_edge(START, "receive_request")
    graph.add_edge("receive_request", "understand_request")
    graph.add_edge("understand_request", "check_missing_context")
    graph.add_conditional_edges(
        "check_missing_context",
        route_after_context,
        {"clarify": "interrupt_for_clarification", "plan": "build_data_requirements"},
    )
    graph.add_edge("interrupt_for_clarification", "understand_request")
    graph.add_edge("build_data_requirements", END)
    return graph.compile()
