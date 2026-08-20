"""记忆层包入口。

对外暴露统一接口 MemoryStore 和降级实现 NoOpMemoryStore。LangGraph 节点
只依赖 MemoryStore，不感知底层是 Mem0 还是 NoOp。
"""

from .base import MemoryRecord, MemoryStore
from .noop import NoOpMemoryStore

__all__ = ["MemoryRecord", "MemoryStore", "NoOpMemoryStore"]
