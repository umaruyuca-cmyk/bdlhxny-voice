"""Query Graph：理解立案、缺口补问、资格菜单构建（重写 §2/§6.2）。

流程：receive → understand
  - missing 非空 → clarify（interrupt）→ understand
  - needs_external=false → END（root 走无工具回答）
  - needs_external=true  → build_allowed_menu → END
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..nodes.nodes import (
    interrupt_for_clarification,
    make_build_allowed_menu_node,
    make_understand_request_node,
    receive_request,
    understand_request,
)
from .state import RootState


def route_after_understand(state: RootState) -> str:
    """理解后：缺口 → 补问；无需外部 → 结束；需要外部 → 建菜单。"""
    understand = state.get("understand", {})
    if understand.get("missing"):
        return "clarify"
    if not understand.get("needs_external", False):
        return "end"
    return "menu"


def build_query_graph(query_agent=None, context_builder=None, registry_snapshot=None):
    """构建理解与菜单子图。

    registry_snapshot 必须由装配层注入（RegistrySnapshot）；
    menu 节点依赖资格真源，禁止默认清单兜底。
    """
    if registry_snapshot is None:
        raise ValueError("build_query_graph requires registry_snapshot (DB catalog source)")

    graph = StateGraph(RootState)
    understand_node = (
        make_understand_request_node(query_agent, context_builder)
        if query_agent is not None
        else understand_request
    )

    graph.add_node("receive_request", receive_request)
    graph.add_node("understand_request", understand_node)
    graph.add_node("interrupt_for_clarification", interrupt_for_clarification)
    graph.add_node("build_allowed_menu", make_build_allowed_menu_node(registry_snapshot))

    graph.add_edge(START, "receive_request")
    graph.add_edge("receive_request", "understand_request")
    graph.add_conditional_edges(
        "understand_request",
        route_after_understand,
        {"clarify": "interrupt_for_clarification", "menu": "build_allowed_menu", "end": END},
    )
    graph.add_edge("interrupt_for_clarification", "understand_request")
    graph.add_edge("build_allowed_menu", END)
    return graph.compile()
