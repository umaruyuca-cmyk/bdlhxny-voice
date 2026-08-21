"""统一业务能力目录。

实施标记：``REWRITE-ENTRY-AND-TOOL-MENU``。目录真源是数据库（经
``RegistrySnapshot`` 加载）；本模块只提供构建视图与查询，**不内置任何
工具清单兜底**（库空由 loader fail-fast 拒绝启动）。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from bdlh_runtime.registry import CapabilityRecord, RegistrySnapshot


class ToolsetName(StrEnum):
    """稳定业务分组名常量（名单真源在库表 bdlh_runtime_toolset）。

    保留 enum 仅作字符串常量；启动时 loader 校验 DB 行，不以此为准。
    """

    MARKET_READ = "market_read"
    FUNDAMENTAL_READ = "fundamental_read"
    NEWS_READ = "news_read"
    PORTFOLIO_READ = "portfolio_read"
    FINANCIAL_PROFILE_READ = "financial_profile_read"
    PLANNING_COMPUTE = "planning_compute"


@dataclass(frozen=True)
class CapabilitySpec:
    """从 DB 行派生的能力视图；供 Graph/Adapter 消费。"""

    name: str
    description: str
    domain: str
    adapter: str
    required_arguments: frozenset[str] = frozenset()
    timeout_seconds: int = 20
    read_only: bool = True
    requires_authenticated_user: bool = False
    depends_on: frozenset[str] = frozenset()
    toolsets: frozenset[str] = frozenset()
    operations: frozenset[str] = frozenset()

    def manifest(self) -> dict[str, object]:
        """返回可安全放入模型上下文的描述；不包含底层路由细节。"""
        return {
            "name": self.name,
            "description": self.description,
            "domain": self.domain,
            "required_arguments": sorted(self.required_arguments),
            "read_only": self.read_only,
            "toolsets": sorted(self.toolsets),
        }

    @classmethod
    def from_record(cls, record: CapabilityRecord) -> CapabilitySpec:
        return cls(
            name=record.name,
            description=record.description,
            domain=record.domain,
            adapter=record.adapter,
            required_arguments=record.required_arguments,
            timeout_seconds=record.timeout_seconds,
            read_only=record.read_only,
            requires_authenticated_user=record.requires_authenticated_user,
            depends_on=record.depends_on,
            toolsets=record.toolsets,
            operations=record.operations,
        )


class CapabilityRegistry:
    """从 RegistrySnapshot 派生的只读能力目录（唯一能力真源视图）。"""

    def __init__(self, specs: Iterable[CapabilitySpec] = ()) -> None:
        self._items: dict[str, CapabilitySpec] = {spec.name: spec for spec in specs}

    def register(self, spec: CapabilitySpec) -> None:
        if spec.name in self._items:
            raise ValueError(f"Capability already registered: {spec.name}")
        if not spec.read_only:
            raise ValueError("Only read-only capabilities may be exposed to research agents")
        self._items[spec.name] = spec

    def get(self, name: str) -> CapabilitySpec:
        try:
            return self._items[name]
        except KeyError as exc:
            raise KeyError(f"Capability is not registered: {name}") from exc

    def contains(self, name: str) -> bool:
        return name in self._items

    def list(self) -> list[CapabilitySpec]:
        return [self._items[name] for name in sorted(self._items)]


def registry_from_snapshot(snapshot: RegistrySnapshot) -> CapabilityRegistry:
    """从已通过启动校验的快照构建能力目录。"""
    return CapabilityRegistry(CapabilitySpec.from_record(record) for record in snapshot.capabilities)


def load_capability_registry(snapshot: RegistrySnapshot) -> CapabilityRegistry:
    """装配入口：唯一合法的目录构建方式（禁止默认清单兜底）。"""
    return registry_from_snapshot(snapshot)
