"""降级记忆实现。

当 Mem0 后端不可用（未部署、连接失败、Embedding 服务宕机）时，使用此实现
顶替。它保证主流程以"无记忆"模式继续运行——search 返回空、add 静默丢弃、

这是架构文档 v3.1 §5.4 "记忆是增强项不是关键路径" 的直接落地：记忆层
挂掉不能拖垮分析流程。LangGraph 节点不感知当前用的是 Mem0 还是 NoOp，
只依赖 MemoryStore 接口。
"""

from __future__ import annotations

import logging
from typing import Any

from .base import MemoryRecord

logger = logging.getLogger("bdlh_runtime.memory")


class NoOpMemoryStore:
    """无操作记忆存储，所有方法返回空结果且不抛异常。"""

    async def search(self, query: str, user_id: str, *, limit: int = 5) -> list[MemoryRecord]:
        """降级语义：无记忆可用，返回空列表。"""
        return []

    async def add(self, content: str, user_id: str, *, metadata: dict[str, Any] | None = None) -> None:
        """显式 noop：不投递、不假装已写入 Outbox。"""
        from .writer import MemoryWriteResult

        del content, user_id, metadata
        logger.debug("记忆 noop：跳过 add")
        return MemoryWriteResult(attempted=False, enqueued=False, skipped_reason="noop")  # type: ignore[return-value]
