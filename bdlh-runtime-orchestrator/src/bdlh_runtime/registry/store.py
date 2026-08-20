"""注册表读取端口的测试替身。

Registry 的 schema、种子和运行时读取均归 Java Data Plane 所有。Python 侧不再
直连 PostgreSQL，也不保留启动建表或 seed 的兼容路径。
"""

from __future__ import annotations

from typing import Protocol

from .models import (
    BudgetRecord,
    CapabilityRecord,
    EntitlementRecord,
    FastpathRouteRecord,
    OperationRecord,
    RegistrySnapshot,
    SkillRecord,
    ToolsetRecord,
    TopicCapabilityRecord,
)


class RegistryStore(Protocol):
    def load(self) -> RegistrySnapshot: ...


class InMemoryRegistryStore:
    """测试显式注入的目录快照构建器。"""

    def __init__(self) -> None:
        self.operations: list[OperationRecord] = []
        self.toolsets: list[ToolsetRecord] = []
        self.capabilities: list[CapabilityRecord] = []
        self.skills: list[SkillRecord] = []
        self.runtime_allowlist: set[str] = set()
        self.entitlements: list[EntitlementRecord] = []
        self.fastpath_routes: list[FastpathRouteRecord] = []
        self.budgets: list[BudgetRecord] = []
        self.topic_capabilities: list[TopicCapabilityRecord] = []

    def load(self) -> RegistrySnapshot:
        return RegistrySnapshot(
            operations=frozenset(self.operations),
            toolsets=frozenset(self.toolsets),
            capabilities=frozenset(self.capabilities),
            skills=frozenset(self.skills),
            runtime_allowlist=frozenset(self.runtime_allowlist),
            entitlements=frozenset(self.entitlements),
            fastpath_routes=frozenset(self.fastpath_routes),
            budgets=frozenset(self.budgets),
            topic_capabilities=frozenset(self.topic_capabilities),
        )
