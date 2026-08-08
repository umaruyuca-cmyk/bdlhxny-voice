"""将外部 Adapter 结果转换为统一 Observation。"""

from __future__ import annotations

from stockwise_analysis.contracts.observation import Observation


class ObservationNormalizer:
    """Phase 2 的标准化入口；禁止将 MCP 原始 JSON 直接传给分析能力。"""

    def normalize(self, observation: Observation) -> Observation:
        """当前契约已经标准化，保留入口供后续字段映射和脱敏扩展。"""

        return observation
