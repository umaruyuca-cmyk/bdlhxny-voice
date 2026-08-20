"""运行定位注册表端口。

生产实现由 Java Data Plane 维护；Python 仅保留测试内存实现，不再持有任何
PostgreSQL 连接、表定义或迁移职责。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bdlh_runtime.runtime.errors import ConfigurationError


@dataclass(frozen=True)
class RunLocation:
    run_id: str
    thread_id: str
    user_id: str | None = None
    checkpoint_id: str | None = None
    runtime_path: str = "cognitive_finance"


class RunRegistry(Protocol):
    def register(self, location: RunLocation) -> None: ...

    def get(self, run_id: str, user_id: str | None = None) -> RunLocation | None: ...


class InMemoryRunRegistry:
    """测试专用实现。"""

    def __init__(self) -> None:
        self._locations: dict[str, RunLocation] = {}

    def register(self, location: RunLocation) -> None:
        self._locations[location.run_id] = location

    def get(self, run_id: str, user_id: str | None = None) -> RunLocation | None:
        location = self._locations.get(run_id)
        if location is None or user_id is None:
            return location
        return location if str(location.user_id) == str(user_id) else None


def create_run_registry(*, environment: str = "test") -> RunRegistry:
    """创建测试用内存索引；运行时数据必须经 Java Data Plane。"""

    if environment != "test":
        raise ConfigurationError("Python 内存 Run Registry 仅允许测试环境")
    return InMemoryRunRegistry()
