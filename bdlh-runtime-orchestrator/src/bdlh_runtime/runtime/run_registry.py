"""运行定位注册表。

API 对外使用 ``run_id``，LangGraph Checkpointer 使用 ``thread_id``。当两者
不相同时，恢复和查询必须先通过本注册表定位真实 thread_id，不能假设二者相等。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RunLocation:
    """一次运行在 Checkpointer 中的定位信息。"""

    run_id: str
    thread_id: str
    user_id: str | None = None
    checkpoint_id: str | None = None


class RunRegistry(Protocol):
    """run_id 到 Checkpointer thread_id 的索引契约。"""

    def register(self, location: RunLocation) -> None:
        """登记一次运行。"""
        ...

    def get(self, run_id: str) -> RunLocation | None:
        """按 run_id 查询运行位置。"""
        ...


class InMemoryRunRegistry:
    """开发/测试实现；生产环境应替换为持久化索引。"""

    def __init__(self) -> None:
        self._locations: dict[str, RunLocation] = {}

    def register(self, location: RunLocation) -> None:
        self._locations[location.run_id] = location

    def get(self, run_id: str) -> RunLocation | None:
        return self._locations.get(run_id)


def create_run_registry() -> RunRegistry:
    """创建运行注册表；当前返回应用级内存实现。"""

    return InMemoryRunRegistry()
