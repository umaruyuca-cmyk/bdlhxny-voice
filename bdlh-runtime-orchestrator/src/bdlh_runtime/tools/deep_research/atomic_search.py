"""Deep 私有原子搜索端口（不得经 Capability Gateway 回调 web_search）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlparse
from uuid import uuid4

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


@dataclass
class FakeAtomicSearchPort:
    """隔离评测用假 Provider；生产路径不得默认注入。"""

    provider_name: str = "fake-bailian"
    unavailable: bool = False
    canned_hits: list[AtomicSearchHit] = field(default_factory=list)

    async def search(self, request: AtomicSearchRequest) -> AtomicSearchBatch:
        if self.unavailable:
            return AtomicSearchBatch(
                request_id=request.request_id,
                status="UNAVAILABLE",
                error_code="ATOMIC_SEARCH_UNAVAILABLE",
                error_message="fake atomic search provider unavailable",
            )
        now = datetime.now(UTC).isoformat()
        if self.canned_hits:
            return AtomicSearchBatch(request_id=request.request_id, status="SUCCESS", hits=list(self.canned_hits))
        hits: list[AtomicSearchHit] = []
        for query in request.queries[: request.max_results]:
            url = f"https://example.test/search?q={uuid4().hex[:8]}"
            hits.append(
                AtomicSearchHit(
                    title=f"Result for {query}",
                    url=url,
                    summary=f"Stub snippet for {query}",
                    domain=urlparse(url).netloc,
                    retrieved_at=now,
                    provider=self.provider_name,
                )
            )
        if not hits:
            return AtomicSearchBatch(
                request_id=request.request_id,
                status="EMPTY",
                error_code="ATOMIC_SEARCH_EMPTY_RESULTS",
            )
        return AtomicSearchBatch(request_id=request.request_id, status="SUCCESS", hits=hits)
