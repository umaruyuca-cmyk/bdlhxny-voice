"""Run 出口 MemoryWriter（ADR-015 / ADR-017 / G7）。

只允许经确认的低影响软偏好写入 L3；禁止 L4 账本字段、checkpoint、持仓等污染。
写入经 Java Outbox，不直连 Mem0。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("bdlh_runtime.memory.writer")

_L4_METADATA_KEYS = frozenset(
    {
        "risk_tolerance",
        "risk_level",
        "max_loss_tolerance_pct",
        "portfolio",
        "positions",
        "account",
        "liquid_assets",
        "checkpoint",
        "checkpoint_id",
        "data_mode",
        "confirmation_ref",
        "broker",
        "order",
        "trade",
    }
)

_L4_CONTENT_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"持仓明细",
        r"账户余额",
        r"风险等级\s*[=:：]",
        r"password\s*=",
        r"api[_-]?key",
        r"bearer\s+",
        r"<conversation",
    )
)


@dataclass(frozen=True)
class MemoryWriteResult:
    attempted: bool
    enqueued: bool
    skipped_reason: str | None = None
    degraded: bool = False


class MemoryWriter:
    """过滤后经 MemoryStore.add → Java Outbox → MQ → Memory Service。"""

    def __init__(self, store: Any) -> None:
        self._store = store

    def filter_candidate(
        self,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]] | None:
        text = (content or "").strip()
        meta = dict(metadata or {})
        if not text or len(text) > 1200:
            return None
        if meta.get("knowledge_type") != "confirmed":
            return None
        if any(key in meta for key in _L4_METADATA_KEYS):
            return None
        if any(pattern.search(text) for pattern in _L4_CONTENT_PATTERNS):
            return None
        # 强制层标注，禁止调用方把 L3 伪造成 L4
        meta = {**meta, "layer": "L3", "knowledge_type": "confirmed"}
        return text, meta

    async def persist(
        self,
        *,
        user_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryWriteResult:
        filtered = self.filter_candidate(content, metadata=metadata)
        if filtered is None:
            return MemoryWriteResult(
                attempted=False,
                enqueued=False,
                skipped_reason="filtered_or_unconfirmed",
            )
        text, meta = filtered
        try:
            result = await self._store.add(text, user_id, metadata=meta)
            if isinstance(result, MemoryWriteResult):
                return result
            # Protocol 约定 add 返回 None 表示尽力投递；Remote 会返回 WriteResult
            return MemoryWriteResult(attempted=True, enqueued=True)
        except Exception as exc:  # noqa: BLE001 — L3 不得阻断主回答
            logger.warning("memory_write_degraded err=%s", type(exc).__name__)
            return MemoryWriteResult(
                attempted=True,
                enqueued=False,
                skipped_reason=type(exc).__name__,
                degraded=True,
            )
