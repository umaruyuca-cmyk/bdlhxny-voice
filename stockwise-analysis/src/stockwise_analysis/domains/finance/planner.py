"""M1 Finance Runtime 的确定性 Planner。"""

from __future__ import annotations

from dataclasses import dataclass

from stockwise_analysis.contracts.data_requirements import DataRequirement
from stockwise_analysis.tools.capabilities import CapabilityRegistry, ToolsetName
from stockwise_analysis.tools.requirement_planner import CapabilityRequirementPlanner
from stockwise_analysis.tools.toolsets import ToolsetRegistry

from .authorization import ANALYSIS_CAPABILITY
from .contracts import FinancialDomainRequest


@dataclass(frozen=True)
class FinancePlan:
    """数据需求和必需确定性分析步骤组成的不可变计划。"""

    data_requirements: tuple[DataRequirement, ...]
    analysis_capability: str = ANALYSIS_CAPABILITY

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(item.capability for item in self.data_requirements) + (
            self.analysis_capability,
        )


class FinancePlanner:
    """从显式请求字段生成数据需求，不读取自由文本关键词。"""

    _M1_TOOLSETS = (
        ToolsetName.MARKET_READ,
        ToolsetName.FUNDAMENTAL_READ,
        ToolsetName.NEWS_READ,
        ToolsetName.PLANNING_COMPUTE,
    )

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry
        self._requirements = CapabilityRequirementPlanner(registry)
        self._toolsets = ToolsetRegistry(registry)

    def plan(self, request: FinancialDomainRequest) -> FinancePlan:
        symbol = request.instruments[0].symbol
        requirements = self._requirements.plan_explicit(
            analysis_type=request.analysis_type,
            symbol=symbol,
            requested_topics=request.requested_topics,
        )
        visible = self._visible_capabilities(request.analysis_type)
        invalid = sorted(
            item.capability for item in requirements
            if item.capability not in visible
        )
        if invalid:
            raise ValueError(
                "Finance plan escaped Toolset boundary: " + ", ".join(invalid)
            )
        if ANALYSIS_CAPABILITY not in visible:
            raise ValueError(f"{ANALYSIS_CAPABILITY} is missing from the planning Toolset")
        return FinancePlan(data_requirements=tuple(requirements))

    def _visible_capabilities(self, analysis_type: str) -> frozenset[str]:
        names: set[str] = set()
        for toolset in self._M1_TOOLSETS:
            names.update(
                item["name"]
                for item in self._toolsets.capability_manifest(
                    toolset,
                    analysis_type=analysis_type,
                )
            )
        return frozenset(names)
