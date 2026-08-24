"""记忆层统一抽象。

所有记忆实现（RemoteMemoryStore、Mem0、测试替身）都遵守这套接口。LangGraph
版只允许 Context Service 在入口读取 search，并由 Run 出口写入 add；
ReAct 循环中不碰记忆——这是保证流程确定性的关键边界（ADR-015）。

为什么用 Protocol 而非 ABC：记忆实现可能是异步的（Mem0 内部调 LLM），
Protocol 允许实现自行决定是否 async，调用方通过统一签名适配。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class MemoryRecord:
    """单条召回的记忆记录。

    content 是记忆正文（研究结论、用户观点等）；metadata 携带来源、时间、
    分数等溯源信息，供 ContextBuilder 第 ⑤ 块和 limitations 使用。

    layer 标注记忆来源层（见 ADR-011 的 L0–L4 分层）：语义记忆固定为 "L3"。
    它只用于观测与审计，不改变召回行为——L3 记忆永远不能驱动高影响规则，
    也不能晋升为业务真源。
    """

    content: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    layer: str = "L3"


class MemoryStore(Protocol):
    """记忆存储统一接口。

    实现必须保证：
    - search 失败时不抛致命异常，返回空结果（降级语义）；
    - add 失败时仅记录日志，不阻塞主流程；
    - 记忆是增强项，不是关键路径——挂了分析照常跑（见架构文档 §5.4）。
    """

    async def search(self, query: str, user_id: str, *, limit: int = 5) -> list[MemoryRecord]:
        """语义召回与 query 相关的历史记忆。失败时返回空列表。"""
        ...

    async def add(self, content: str, user_id: str, *, metadata: dict[str, Any] | None = None) -> None:
        """沉淀一条记忆。失败时仅记日志，不抛异常。"""
        ...
