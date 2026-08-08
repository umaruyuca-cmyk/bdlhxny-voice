"""MCP 原始工具到内部统一能力的适配边界。"""

from __future__ import annotations

from typing import Protocol

from stockwise_analysis.contracts.observation import Observation


class McpAdapter(Protocol):
    """将一个 MCP 服务适配为受控内部工具。"""

    async def execute(self, capability: str, arguments: dict) -> Observation:
        """执行统一能力并返回标准化 Observation。"""
