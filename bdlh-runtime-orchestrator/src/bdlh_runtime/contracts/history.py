"""分析历史记录契约（v2.1 §9.3）。

Analysis History 与 Conversation State / Checkpointer / Long-term Memory 严格区分：
- Conversation State：当前对话状态（LangGraph State）
- Checkpointer：中断恢复
- Analysis History：历史分析记录与审计（本契约）
- Long-term Memory：用户长期偏好（Mem0）
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AnalysisHistoryRecord(BaseModel):
    """一次分析运行的历史记录（审计 + 历史查询）。

    保存范围/查询权限/保留期限/脱敏策略由存储层实现（见 runtime/history.py）。
    """

    history_id: str
    thread_id: str
    run_id: str
    authenticated_user_id: str | None = None
    request_snapshot: dict[str, Any] = Field(default_factory=dict)
    intent_snapshot: dict[str, Any] = Field(default_factory=dict)
    plan_version: int | None = None
    observations_summary: list[dict[str, Any]] = Field(default_factory=list)
    analysis_result: dict[str, Any] | None = None
    source_timestamps: list[str] = Field(default_factory=list)
    status: Literal["SUCCESS", "PARTIAL", "LIMITED", "FAILED", "RUNNING"] = "RUNNING"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    retention_policy: str = "default"
