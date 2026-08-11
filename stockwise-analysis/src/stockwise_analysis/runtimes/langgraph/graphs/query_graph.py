"""Query Graph：理解问题、执行模式选择、补充上下文并生成动态数据需求（v2.1 §3）。"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..nodes.nodes import (
    build_data_requirements,
    check_missing_context,
    make_understand_request_node,
    understand_request,
    interrupt_for_clarification,
    receive_request,
    route_execution,
)
from .state import RootState


def route_after_route(state: RootState) -> str:
    """执行模式选择后：direct_response 直接结束；其他进入上下文检查。

    direct_response 是知识问答，不需要标的，不检查上下文直接回答。
    single_capability / agent_loop 才检查是否缺关键信息。
    """
    mode = state.get("intent_route", {}).get("mode", "agent_loop")
    return "end" if mode == "direct_response" else "check"


def route_after_context(state: RootState) -> str:
    """缺少关键信息时暂停；完整时才允许进入数据规划。"""
    return "clarify" if state.get("needs_clarification") else "plan"


def build_query_graph(query_agent=None, context_builder=None):
    """构建问题理解子图（v2.1 §3 含执行模式选择）。

    流程：understand → route_execution
      - direct_response → END（root_graph 接 direct_response_node 直接回答，不检查上下文）
      - single_capability / agent_loop → check_missing → build_data_requirements → END

    route_execution 在 check_missing 之前：知识问答直接回答，不因缺 symbol 中断。
    """

    graph = StateGraph(RootState)
    understand_node = (
        make_understand_request_node(query_agent, context_builder)
        if query_agent is not None
        else understand_request
    )

    graph.add_node("receive_request", receive_request)
    graph.add_node("understand_request", understand_node)
    graph.add_node("route_execution", route_execution)
    graph.add_node("check_missing_context", check_missing_context)
    graph.add_node("interrupt_for_clarification", interrupt_for_clarification)
    graph.add_node("build_data_requirements", build_data_requirements)

    graph.add_edge(START, "receive_request")
    graph.add_edge("receive_request", "understand_request")
    graph.add_edge("understand_request", "route_execution")
    # direct_response 直接 END；其他检查上下文
    graph.add_conditional_edges(
        "route_execution",
        route_after_route,
        {"end": END, "check": "check_missing_context"},
    )
    graph.add_conditional_edges(
        "check_missing_context",
        route_after_context,
        {"clarify": "interrupt_for_clarification", "plan": "build_data_requirements"},
    )
    graph.add_edge("interrupt_for_clarification", "understand_request")
    graph.add_edge("build_data_requirements", END)
    return graph.compile()
