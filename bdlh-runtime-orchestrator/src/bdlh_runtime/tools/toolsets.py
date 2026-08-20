"""基于统一 Capability Registry 的 Toolset 派生视图。

实施标记：``REWRITE-ENTRY-AND-TOOL-MENU``。本模块不保存第二份 Capability
规格：它持有 ``CapabilityRegistry``（由 RegistrySnapshot 构建）的引用，
按 ``CapabilitySpec.toolsets`` 动态分组；描述来自库表
``bdlh_runtime_toolset``，禁止在代码里维护第二份描述字典。
"""

from __future__ import annotations

from dataclasses import dataclass

from bdlh_runtime.registry import RegistrySnapshot

from .capabilities import CapabilityRegistry, CapabilitySpec, registry_from_snapshot


@dataclass(frozen=True)
class ToolsetSpec:
    """某个 Toolset 在当前 Capability Registry 上的动态投影视图。"""

    name: str
    description: str
    capabilities: tuple[CapabilitySpec, ...]

    def selection_manifest(self) -> dict[str, object]:
        """返回给第一层选择器的最小描述，不展开底层能力。"""

        return {
            "name": self.name,
            "description": self.description,
            "capability_count": len(self.capabilities),
        }


class ToolsetRegistry:
    """从一个 ``CapabilityRegistry`` 动态派生的只读分组注册表。"""

    def __init__(self, capability_registry: CapabilityRegistry, descriptions: dict[str, str]) -> None:
        self._capability_registry = capability_registry
        self._descriptions = descriptions

    @property
    def capability_registry(self) -> CapabilityRegistry:
        """返回唯一能力真源，供装配层验证对象身份。"""

        return self._capability_registry

    def _validate_grouping(self) -> None:
        ungrouped = [spec.name for spec in self._capability_registry.list() if not spec.toolsets]
        if ungrouped:
            joined = ", ".join(ungrouped)
            raise ValueError(f"Capabilities missing toolset membership: {joined}")

    def get(self, name: str) -> ToolsetSpec:
        self._validate_grouping()
        if name not in self._descriptions:
            raise KeyError(f"Toolset is not registered: {name}")
        capabilities = tuple(spec for spec in self._capability_registry.list() if name in spec.toolsets)
        return ToolsetSpec(
            name=name,
            description=self._descriptions[name],
            capabilities=capabilities,
        )

    def list(self) -> list[ToolsetSpec]:
        """列出全部分组；分组内容始终从 Capability Registry 现算。"""

        return [self.get(name) for name in sorted(self._descriptions)]

    def selection_manifest(self) -> list[dict[str, object]]:
        """仅暴露 Toolset 层，避免一次向模型展示全部 Capability。"""

        return [spec.selection_manifest() for spec in self.list()]

    def capability_manifest(self, name: str) -> list[dict[str, object]]:
        """选择 Toolset 后展开该组的安全 Capability 描述（无类型过滤）。"""
        return [spec.manifest() for spec in self.get(name).capabilities]


def toolset_registry_from_snapshot(snapshot: RegistrySnapshot) -> ToolsetRegistry:
    """从已通过启动校验的快照派生 Toolset 视图（描述读库）。"""
    descriptions = {record.name: record.description for record in snapshot.toolsets}
    registry = ToolsetRegistry(registry_from_snapshot(snapshot), descriptions)
    registry.list()
    return registry


def load_toolset_registry(snapshot: RegistrySnapshot) -> ToolsetRegistry:
    """装配入口：唯一合法的 Toolset 视图构建方式。"""
    return toolset_registry_from_snapshot(snapshot)
