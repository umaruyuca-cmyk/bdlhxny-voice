"""工具执行运行时。"""

from __future__ import annotations

import inspect
from typing import Any

from .models import ToolResult
from .registry import ToolRegistry


class ToolRuntime:
    """统一执行工具，并把异常转换为结构化 ToolResult。"""
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def invoke(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """执行白名单内的单个工具；不让异常逃出 Graph 节点。"""
        spec = self.registry.get(tool_name)
        try:
            value = spec.handler(arguments)
            if inspect.isawaitable(value):
                value = await value
            return ToolResult(tool_name=tool_name, status="SUCCESS", data=value)
        except Exception as exc:  # Runtime converts failures into structured results.
            return ToolResult(tool_name=tool_name, status="FAILED", error_code="TOOL_ERROR", error_message=str(exc))
