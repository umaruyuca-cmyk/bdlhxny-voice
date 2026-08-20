"""统一工具白名单。

Research Agent 未来只能看见本 Registry 暴露的统一能力，不能看见原始 MCP
工具名、连接信息或任意 HTTP URL。
"""

from __future__ import annotations

from .models import ToolHandler, ToolSpec


class ToolRegistry:
    """工具白名单；Agent 不得直接获得原始 MCP 工具名。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self, name: str, description: str, handler: ToolHandler, *, read_only: bool = True, timeout_seconds: int = 20
    ) -> None:
        """注册只读工具；第一阶段拒绝任何写操作。"""
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        if not read_only:
            raise ValueError("The first workflow version only permits read-only tools")
        self._tools[name] = ToolSpec(
            name=name, description=description, handler=handler, read_only=read_only, timeout_seconds=timeout_seconds
        )

    def get(self, name: str) -> ToolSpec:
        """按统一工具名获取工具定义。"""
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Tool is not registered: {name}") from exc

    def list(self) -> list[ToolSpec]:
        """返回当前允许暴露的工具集合。"""
        return list(self._tools.values())
