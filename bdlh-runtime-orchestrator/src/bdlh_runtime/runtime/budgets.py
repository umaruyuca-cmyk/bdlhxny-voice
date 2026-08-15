"""流程运行预算。

预算由 Runtime 统一维护；Agent 只能提出下一步动作，不能自行延长时间或
工具调用次数。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisBudget:
    """单个 analysis_type 的有界执行预算。"""

    react_round_limit: int
    tool_call_limit: int
    subgraph_timeout_seconds: int
    request_timeout_seconds: int


ANALYSIS_BUDGETS: dict[str, AnalysisBudget] = {
    "market_snapshot": AnalysisBudget(0, 3, 25, 40),
    "technical": AnalysisBudget(4, 5, 45, 70),
    "fundamental": AnalysisBudget(5, 7, 55, 90),
    "valuation": AnalysisBudget(4, 5, 45, 70),
    "portfolio_impact": AnalysisBudget(6, 8, 60, 100),
    "comprehensive": AnalysisBudget(10, 14, 150, 240),
}


def budget_for(analysis_type: str) -> AnalysisBudget:
    """返回分析类型预算；未知类型使用快路径安全默认值。"""

    return ANALYSIS_BUDGETS.get(analysis_type, ANALYSIS_BUDGETS["market_snapshot"])
