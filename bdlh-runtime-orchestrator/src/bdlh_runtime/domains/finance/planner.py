"""Finance Runtime 的确定性 Planner（重写：requested_topics 驱动）。

不再按类型桶展开工具链；数据需求由「resolve/quote 基线 + topic 对照能力 +
depends_on 闭包 + 确定性分析」组成。topic→能力对照来自库表
（``bdlh_runtime_topic_capability``，经 RegistrySnapshot 派生注入）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bdlh_runtime.contracts.data_requirements import DataRequirement

from .authorization import ANALYSIS_CAPABILITY
from .contracts import FinancialDomainRequest

_QUOTE_CAPABILITY = "market.get_realtime_quote"
_RESOLVE_CAPABILITY = "market.resolve_instrument"


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
    """从显式请求字段（topics + instruments）生成数据需求，不读自由文本。"""

    def __init__(self, topic_capabilities: dict[str, list[str]]) -> None:
        self._topic_capabilities = topic_capabilities

    def plan(self, request: FinancialDomainRequest) -> FinancePlan:
        names: list[str] = []
        for instrument in request.instruments:
            symbol = instrument.symbol
            names.append(_RESOLVE_CAPABILITY)
            names.append(_QUOTE_CAPABILITY)
            for topic in sorted(request.requested_topics):
                for capability in self._topic_capabilities.get(topic, []):
                    if capability not in (_RESOLVE_CAPABILITY, _QUOTE_CAPABILITY):
                        names.append(capability)
            # 去重保序
            seen: set[str] = set()
            ordered = [n for n in names if not (n in seen or seen.add(n))]
            names = ordered
        requirements = tuple(
            DataRequirement(
                requirement_id=f"cap-{index}-{name.replace('.', '-')}",
                capability=name,
                required=True,
                reason=f"Finance plan for {instrument.symbol}",
                arguments=self._arguments(name, request),
            )
            for index, name in enumerate(dict.fromkeys(names))
        )
        return FinancePlan(data_requirements=requirements)

    @staticmethod
    def _arguments(name: str, request: FinancialDomainRequest) -> dict:
        if name == _QUOTE_CAPABILITY or name == _RESOLVE_CAPABILITY or name.startswith("market."):
            return {"symbol": request.instruments[0].symbol}
        if name == "research.web_search":
            topic = request.instruments[0].symbol
            return {"query": f"{topic} 最新动态", "mode": "NEWS", "max_results": 5}
        return {}
