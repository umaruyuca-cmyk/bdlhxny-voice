"""Query Graph：负责理解问题、补充上下文并生成动态数据需求。"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import (
    build_data_requirements,
    check_missing_context,
    understand_request,
    interrupt_for_clarification,
    receive_request,
)
from .state import RootState


def route_after_context(state: RootState) -> str:
    """缺少关键信息时暂停；完整时才允许进入数据规划。"""
    return "clarify" if state.get("needs_clarification") else "plan"


def build_query_graph():
    """构建问题理解子图。

    当前使用确定性解析验证流程边界；后续替换为 Query Agent 时，只替换
    ``understand_request`` 节点，不改变 interrupt 和计划契约。
    """

    graph = StateGraph(RootState)
    graph.add_node("receive_request", receive_request)
    graph.add_node("understand_request", understand_request)
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
