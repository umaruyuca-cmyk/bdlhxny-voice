"""受控工具的契约定义。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

ToolHandler = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


class ToolSpec(BaseModel):
    """注册到 Tool Registry 的统一工具描述。"""

    name: str
    description: str
    read_only: bool = True
    timeout_seconds: int = 20
    handler: Any = Field(exclude=True)


class ToolResult(BaseModel):
    """Tool Runtime 返回的结构化执行结果。"""

    tool_name: str
    status: str
    data: Any = None
    error_code: str | None = None
    error_message: str | None = None
