"""Deep Research 请求 / ResearchBundle 契约（00 Prompt §6.5.5–6.5.6）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DEEP_SEARCH_CAPABILITY = "research.deep_search"
WEB_SEARCH_CAPABILITY = "research.web_search"

ResearchBundleStatus = Literal[
    "COMPLETE",
    "PARTIAL",
    "LIMITED",
    "FAILED",
    "NEEDS_CLARIFICATION",
]


class DeepResearchBudget(BaseModel):
    """一次 Deep 调用的内部预算上限（外层仍计为一次 Capability）。"""

    model_config = ConfigDict(extra="forbid")

    runtime_seconds: int = Field(default=90, ge=1)
    model_call_limit: int = Field(default=24, ge=1)
    search_call_limit: int = Field(default=20, ge=1)
    max_concurrent_research_units: int = Field(default=3, ge=1)
    max_supervisor_iterations: int = Field(default=6, ge=1)
    max_react_tool_calls: int = Field(default=8, ge=1)


class DeepResearchRequest(BaseModel):
    """调用方 Agent 已整理的研究任务；禁止携带模型名 / Key / MCP 配置。"""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    success_criteria: list[str] = Field(default_factory=list)
    # 与入口 Goal 的 requested_topics（news|…）命名空间独立
    research_topics: list[str] = Field(default_factory=list)
    time_range: str | None = None
    language: str = "zh-CN"
    include_domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)
    budget: DeepResearchBudget = Field(default_factory=DeepResearchBudget)


class ResearchFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    statement: str
    source_ids: list[str] = Field(default_factory=list)
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"


class ResearchSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str
    url: str
    domain: str = ""
    published_at: str | None = None
    retrieved_at: str
    summary: str = ""
    source_type: str = "web"


class ResearchUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_calls: int = 0
    search_calls: int = 0
    research_units: int = 0
    duration_ms: int = 0
    budget_exhausted: bool = False


class ResearchBundle(BaseModel):
    """供调用 Agent 消费的结构化研究资料，不是客户最终文案。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "research-bundle.v1"
    request_id: str
    question: str
    research_brief: str = ""
    status: ResearchBundleStatus
    findings: list[ResearchFinding] = Field(default_factory=list)
    sources: list[ResearchSource] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    research_summary: str = ""
    clarification_questions: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    usage: ResearchUsage = Field(default_factory=ResearchUsage)
    deep_trigger_reasons: list[str] = Field(default_factory=list)
