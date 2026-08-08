"""Java 用户数据 API 适配边界。"""

from __future__ import annotations

from typing import Protocol

from stockwise_analysis.contracts.observation import Observation


class JavaDataAdapter(Protocol):
    """用户持仓、账户和风险偏好必须经由 Java 服务读取。"""

    async def execute(self, capability: str, arguments: dict) -> Observation:
        """调用白名单 Java Data API 并转换为 Observation。"""
