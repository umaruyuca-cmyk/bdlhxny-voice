"""外部数据标准化契约。

MCP、Java 与未来的记忆服务都必须先转换为 Observation，原始响应不得直接
拼入模型上下文或 AnalysisInput。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ProvenanceRecord(BaseModel):
    """数据来源、工具调用和回退信息（审查文档 §6.1：溯源字段补全）。

    字段对齐审查要求：
    - source：MCP 名称 / java-api / mock；
    - tool：原始工具名（如 get_realtime_quote）；
    - elapsed_ms：响应耗时（毫秒，审计性能用）；
    - fallback_used：是否使用备用源；
    - conflict_detected：是否发生字段冲突（多源对照时）；
    - raw_reference：原始响应引用（受控引用，不直接进 AnalysisInput）。
    """

    source: str
    tool: str
    request_id: str | None = None
    as_of: str | None = None
    retrieved_at: str
    elapsed_ms: int | None = None
    fallback_used: bool = False
    conflict_detected: bool = False
    raw_reference: str | None = None


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
    result_type: str | None = None
    payload: dict[str, Any] | None = None
