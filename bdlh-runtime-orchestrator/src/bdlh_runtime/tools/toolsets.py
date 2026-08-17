"""基于统一 Capability Registry 的 Toolset 派生视图。

实施标记：``SW31-TOOLSET-VIEW``。

本模块不保存第二份 Capability 规格。它持有现有 ``CapabilityRegistry`` 的
引用，并在读取时根据 ``CapabilitySpec.toolsets`` 动态分组。上层先只看六个
Toolset，选中后再展开本组且符合分析类型的统一 Capability。
"""

from __future__ import annotations

from dataclasses import dataclass

from .capabilities import (
    CapabilityRegistry,
    CapabilitySpec,
    ToolsetName,
    build_default_capability_registry,
)


_TOOLSET_DESCRIPTIONS: dict[ToolsetName, str] = {
    ToolsetName.MARKET_READ: "读取标的、行情、历史价格和资金流数据",
    ToolsetName.FUNDAMENTAL_READ: "读取财务报表、估值和行业背景数据",
    ToolsetName.NEWS_READ: "读取结构化新闻和外部公开资料",
    ToolsetName.PORTFOLIO_READ: "只读访问当前用户持仓、账户和交易历史",
    ToolsetName.FINANCIAL_PROFILE_READ: "只读访问当前用户风险画像和金融档案",
    ToolsetName.PLANNING_COMPUTE: "对标准化数据执行确定性金融计算",
    ToolsetName.PLUGIN_PROBE_COMPUTE: "执行无外部调用的插件契约探针",
}


@dataclass(frozen=True)
class ToolsetSpec:
    """某个 Toolset 在当前 Capability Registry 上的动态投影视图。"""

    name: ToolsetName
    description: str
    capabilities: tuple[CapabilitySpec, ...]

    def selection_manifest(self) -> dict[str, object]:
        """返回给第一层选择器的最小描述，不展开底层能力。"""

        return {
            "name": self.name.value,
            "description": self.description,
            "capability_count": len(self.capabilities),
        }


class ToolsetRegistry:
    """从一个 ``CapabilityRegistry`` 动态派生的只读分组注册表。"""

    def __init__(self, capability_registry: CapabilityRegistry) -> None:
        self._capability_registry = capability_registry

    @property
    def capability_registry(self) -> CapabilityRegistry:
        """返回唯一能力真源，供装配层验证对象身份。"""

        return self._capability_registry

    def _validate_grouping(self) -> None:
        ungrouped = [
            spec.name
            for spec in self._capability_registry.list()
            if not spec.toolsets
        ]
        if ungrouped:
            joined = ", ".join(ungrouped)
            raise ValueError(f"Capabilities missing toolset membership: {joined}")

    def get(self, name: ToolsetName | str) -> ToolsetSpec:
        self._validate_grouping()
        try:
            toolset_name = ToolsetName(name)
        except ValueError as exc:
            raise KeyError(f"Toolset is not registered: {name}") from exc

        capabilities = tuple(
            spec
            for spec in self._capability_registry.list()
            if toolset_name in spec.toolsets
        )
        return ToolsetSpec(
            name=toolset_name,
            description=_TOOLSET_DESCRIPTIONS[toolset_name],
            capabilities=capabilities,
        )

    def list(self) -> list[ToolsetSpec]:
        """列出六个稳定分组；分组内容始终从 Capability Registry 现算。"""

        return [self.get(name) for name in ToolsetName]

    def selection_manifest(self) -> list[dict[str, object]]:
        """仅暴露 Toolset 层，避免一次向模型展示全部 Capability。"""

        return [spec.selection_manifest() for spec in self.list()]

    def capability_manifest(
        self,
        name: ToolsetName | str,
        *,
        analysis_type: str | None = None,
    ) -> list[dict[str, object]]:
        """选择 Toolset 后按当前分析类型展开安全 Capability 描述。"""

        specs = self.get(name).capabilities
        if analysis_type is not None:
            specs = tuple(
                spec
                for spec in specs
                if analysis_type in spec.analysis_types
            )
        return [spec.manifest() for spec in specs]


def build_default_toolset_registry(
    capability_registry: CapabilityRegistry | None = None,
) -> ToolsetRegistry:
    """使用现有或默认 Capability Registry 创建派生 Toolset 视图。"""

    source = capability_registry or build_default_capability_registry()
    registry = ToolsetRegistry(source)
    registry.list()
    return registry
