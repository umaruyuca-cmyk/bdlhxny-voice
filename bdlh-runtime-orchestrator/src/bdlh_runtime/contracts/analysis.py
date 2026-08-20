"""Analysis Capability 的输入输出契约。

该契约使 Python Analysis Engine 与未来可选的独立 Skill 服务可以互换，且都
不得在分析阶段补查外部数据。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .observation import DataQuality, ProvenanceRecord


class InstrumentRef(BaseModel):
    """统一标的标识。"""

    symbol: str
    name: str | None = None
    market: str = "CN"
    exchange: str | None = None
    instrument_type: str = "stock"


class AnalysisInput(BaseModel):
    """纯分析输入；只包含已经标准化和带来源的数据。"""

    schema_version: str = "analysis-input.v1"
    analysis_id: str
    instrument: InstrumentRef
    realtime_quote: dict[str, Any] | None = None
    historical_prices: list[dict[str, Any]] = Field(default_factory=list)
    financial_data: dict[str, Any] | None = None
    valuation_data: dict[str, Any] | None = None
    industry_context: dict[str, Any] | None = None
    money_flow_data: dict[str, Any] | None = None
    news_context: list[dict[str, Any]] = Field(default_factory=list)
    portfolio_context: dict[str, Any] | None = None
    overseas_context: dict[str, Any] | None = None
    data_quality: DataQuality = Field(default_factory=DataQuality)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)
    methodology_version: str = "python-analysis.v1"


class AnalysisResult(BaseModel):
    """纯分析输出；必须携带限制、质量和溯源信息。"""

    schema_version: str = "analysis-result.v1"
    analysis_id: str
    status: Literal["SUCCESS", "PARTIAL", "LIMITED", "FAILED"]
    facts: list[dict[str, Any]] = Field(default_factory=list)
    calculated_indicators: dict[str, Any] = Field(default_factory=dict)
    signals: list[dict[str, Any]] = Field(default_factory=list)
    risk_flags: list[dict[str, Any]] = Field(default_factory=list)
    conclusions: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    data_quality: DataQuality = Field(default_factory=DataQuality)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)
    methodology_version: str = "python-analysis.v1"
