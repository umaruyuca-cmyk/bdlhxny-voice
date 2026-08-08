"""数据需求契约。

Query Graph 只声明“需要什么数据”，不直接决定 MCP 的原始工具、连接方式或
数据源路由。后续由 MarketDataGateway 将统一能力映射为实际 MCP 调用。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DataRequirement(BaseModel):
    """单项数据需求及其完成状态。"""

    requirement_id: str
    capability: str
    required: bool = True
    reason: str
    arguments: dict = Field(default_factory=dict)
    status: Literal["PENDING", "AVAILABLE", "UNAVAILABLE", "SKIPPED"] = "PENDING"
