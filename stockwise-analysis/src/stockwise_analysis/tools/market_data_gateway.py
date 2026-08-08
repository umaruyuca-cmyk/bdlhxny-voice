"""统一市场数据网关边界。

Graph 和 Research Agent 只认识 ``market.*`` 统一能力。Gateway 根据配置调用
底层 MCP Adapter、执行主备路由并返回标准化 Observation，不暴露连接细节。
"""

from __future__ import annotations

from typing import Protocol

from stockwise_analysis.contracts.observation import Observation


class MarketDataGateway(Protocol):
    """Phase 2 真实市场数据网关接口。"""

    async def execute(self, capability: str, arguments: dict) -> Observation:
        """执行一个统一市场能力，并在内部处理路由、超时与降级。"""
