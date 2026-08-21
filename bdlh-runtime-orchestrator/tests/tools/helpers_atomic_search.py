"""Tests-only FakeAtomicSearchPort — not a product path."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import uuid4

from bdlh_runtime.tools.deep_research.atomic_search import (
    AtomicSearchBatch,
    AtomicSearchHit,
    AtomicSearchRequest,
)


@dataclass
class FakeAtomicSearchPort:
    """隔离评测用假 Provider。"""

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
