"""流程事件契约。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class WorkflowEvent(BaseModel):
    """用于 SSE、运行审计和故障追踪的事件模型。"""
    event_id: str
    event_type: str
    node: str
    run_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: dict[str, Any] = Field(default_factory=dict)
