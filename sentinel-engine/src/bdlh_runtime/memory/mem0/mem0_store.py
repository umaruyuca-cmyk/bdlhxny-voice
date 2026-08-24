"""Mem0 记忆实现。

Mem0 内部会用 LLM 做"抽取要点 + 去重更新 + 重排"三件事，记忆质量优于裸
向量化。但这些内部调用带来额外开销和故障面，因此本实现严格遵循架构文档
v3.1 §5.4 的工程约束：

1. 内部 LLM 显式配 DeepSeek，不用 Mem0 默认 OpenAI（避免未声明依赖）；
2. Embedding 显式配 Qwen3；
3. 所有操作 try-except，失败时降级为空结果，绝不抛致命异常；
4. search/add 耗时由调用方计入运行预算。

产品装配使用 RemoteMemoryStore，不经本模块工厂降级。
"""

from __future__ import annotations

import logging
from typing import Any

from ..base import MemoryRecord

logger = logging.getLogger("bdlh_runtime.memory.mem0")


class Mem0MemoryStore:
    """基于 Mem0 的记忆存储实现。

    Mem0 客户端在 __init__ 时初始化；调用方负责确保依赖可用。
    """

    def __init__(self, mem0_client: Any):
        """注入已初始化的 Mem0 client。L4 profile 不属于此 Port。"""
        self._client = mem0_client

    async def search(self, query: str, user_id: str, *, limit: int = 5) -> list[MemoryRecord]:
        """语义召回相关记忆。Mem0 失败时返回空列表（降级语义）。"""
        try:
            results = self._client.search(query=query, user_id=user_id, limit=limit)
            # Mem0 返回格式：list[dict]，每条含 memory/score/user_id 等
            return [
                MemoryRecord(
                    content=item.get("memory", item.get("content", "")),
                    score=float(item.get("score", 0.0)),
                    metadata={k: v for k, v in item.items() if k not in ("memory", "content", "score")},
                )
                for item in (results or [])
            ]
        except Exception as exc:
            logger.warning("Mem0 search 降级返回空 (user_id=%s): %s", user_id, exc)
            return []

    async def add(self, content: str, user_id: str, *, metadata: dict[str, Any] | None = None) -> None:
        """沉淀记忆。Mem0 内部会抽取要点并去重。失败时仅记日志不抛异常。"""
        try:
            self._client.add(content, user_id=user_id, metadata=metadata or {})
        except Exception as exc:
            logger.warning("Mem0 add 失败已忽略 (user_id=%s): %s", user_id, exc)
