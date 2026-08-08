"""外部数据标准化契约。

MCP、Java 与未来的记忆服务都必须先转换为 Observation，原始响应不得直接
拼入模型上下文或 AnalysisInput。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ProvenanceRecord(BaseModel):
    """数据来源、工具调用和回退信息。"""
    source: str
    tool: str
    request_id: str | None = None
    as_of: str | None = None
    retrieved_at: str
    fallback_used: bool = False


class DataQuality(BaseModel):
    """数据完整度、新鲜度和已知不可用维度。"""
    completeness: float = 0.0
    freshness: str = "UNKNOWN"
    quality_status: Literal["UNKNOWN", "OK", "PARTIAL", "STALE", "INVALID"] = "UNKNOWN"
    known_unavailable: list[str] = Field(default_factory=list)


class Observation(BaseModel):
    """统一的外部调用结果。"""
    observation_id: str
    capability: str
    status: Literal["SUCCESS", "PARTIAL", "FAILED", "UNAVAILABLE"]
    data: Any = None
    data_quality: DataQuality = Field(default_factory=DataQuality)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
