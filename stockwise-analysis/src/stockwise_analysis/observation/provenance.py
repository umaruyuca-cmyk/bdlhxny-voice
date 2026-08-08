"""数据溯源记录辅助函数。"""

from __future__ import annotations

from datetime import datetime, timezone

from stockwise_analysis.contracts.observation import ProvenanceRecord


def provenance(source: str, tool: str, *, request_id: str | None = None, fallback_used: bool = False) -> ProvenanceRecord:
    """创建统一 UTC 溯源记录。"""

    return ProvenanceRecord(
        source=source,
        tool=tool,
        request_id=request_id,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        fallback_used=fallback_used,
    )
