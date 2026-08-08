"""远程 MCP Client 抽象。"""

from __future__ import annotations

from typing import Any, Protocol


class McpClient(Protocol):
    """单个 MCP 服务连接；Gateway 不得绕过 Adapter 直接持有它。"""

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用 MCP 原始工具并返回原始响应，标准化由 Adapter 负责。"""
