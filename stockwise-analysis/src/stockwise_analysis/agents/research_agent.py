"""Research Agent 的行动契约。

Phase 2 接入真实 MCP 后，该 Agent 只能提出一个统一工具动作；Tool Runtime 和
MarketDataGateway 负责实际执行、预算和数据源路由。
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class ResearchAction(BaseModel):
    """有界 ReAct 单轮允许输出的唯一行动。"""

    action: str
    arguments: dict = Field(default_factory=dict)
    reason: str


class ResearchAgent(Protocol):
    """市场数据子图的有界 Agent 接口。"""

    def choose_next_action(self, observations: list[dict], remaining_requirements: list[dict]) -> ResearchAction:
        """仅提出一个只读统一工具动作；不得直接执行工具。"""
