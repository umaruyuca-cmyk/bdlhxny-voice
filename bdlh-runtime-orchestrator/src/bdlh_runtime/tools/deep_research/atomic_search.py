"""Deep 私有原子搜索端口（不得经 Capability Gateway 回调 web_search）。"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class AtomicSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    queries: list[str] = Field(min_length=1)
    mode: str = "web"
    freshness: str | None = None
    include_domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)
    max_results: int = Field(default=5, ge=1, le=20)


class AtomicSearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    url: str
    summary: str = ""
    domain: str = ""
    published_at: str | None = None
    retrieved_at: str
    provider: str = "bailian"


class AtomicSearchBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    status: str = "SUCCESS"  # SUCCESS | EMPTY | UNAVAILABLE
    hits: list[AtomicSearchHit] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


class AtomicSearchPort(Protocol):
    async def search(self, request: AtomicSearchRequest) -> AtomicSearchBatch:
        """一次或一批受控网页检索；不负责任何研究完成判断。"""
        ...
