"""Java 用户数据 API 适配器。

用户持仓、账户和风险偏好必须经由 Java 服务读取（架构文档 v3.1 §13.3）：
Python 不允许绕过 Java API 直接读取用户业务表。

设计原则（与 MCP adapter 一致）：
- 统一能力 → Java HTTP API 的翻译在 Adapter 内完成；
- Java 返回结果转换为 Observation，不允许 Graph 节点直接拼接 Java JSON；
- 降级：Java 服务不可用（未部署/超时）时返回 mock 持仓，保证开发环境
  和测试可跑通完整流程。mock 数据带 is_mock 标记，不伪装成真实数据。
"""

from __future__ import annotations

import logging
from typing import Any, Protocol
from uuid import uuid4

from stockwise_analysis.contracts.observation import DataQuality, Observation, ProvenanceRecord

logger = logging.getLogger("stockwise_analysis.tools.java")


class JavaDataAdapter(Protocol):
    """用户持仓、账户和风险偏好必须经由 Java 服务读取。"""

    async def execute(self, capability: str, arguments: dict) -> Observation:
        """调用白名单 Java Data API 并转换为 Observation。"""


# Java 白名单能力（架构文档 §13.3），Adapter 只允许这些
JAVA_CAPABILITIES = {
    "portfolio.get_current_positions",
    "portfolio.get_account_snapshot",
    "portfolio.get_transaction_history",
    "user.get_risk_profile",
}


class HttpJavaDataAdapter:
    """通过 HTTP 调用 Java 用户数据服务的实现。

    Java 服务未部署（endpoint 为空）或调用失败时，降级为 mock 持仓
    （带 is_mock 标记）。降级不阻断流程——持仓是增强信息，不是关键路径。
    """

    def __init__(self, base_url: str | None = None, timeout_seconds: float = 10.0):
        """base_url 为 Java API 根地址；None 时直接走 mock 降级。"""
        self._base_url = base_url
        self._timeout = timeout_seconds

    async def execute(self, capability: str, arguments: dict) -> Observation:
        if capability not in JAVA_CAPABILITIES:
            return self._failed_observation(capability, f"Java 白名单外能力: {capability}")

        # Java 服务未配置 → mock 降级
        if not self._base_url:
            return self._mock_observation(capability, arguments)

        # 真实调用 Java API
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url.rstrip('/')}/api/{capability}",
                    params={"user_id": arguments.get("user_id")},
                )
                resp.raise_for_status()
                data = resp.json()
                return Observation(
                    observation_id=str(uuid4()),
                    capability=capability,
                    status="SUCCESS",
                    data=data,
                    data_quality=DataQuality(completeness=1.0, quality_status="OK"),
                    provenance=[ProvenanceRecord(source="java-api", tool=capability, retrieved_at=_now_iso())],
                )
        except Exception as exc:
            logger.warning("Java API 调用失败 (capability=%s)，降级 mock: %s", capability, exc)
            return self._mock_observation(capability, arguments)

    # ── mock 降级实现（开发环境/测试用，带 is_mock 标记）──

    def _mock_observation(self, capability: str, arguments: dict) -> Observation:
        user_id = arguments.get("user_id") or "unknown"
        data = _MOCK_DATA.get(capability, {})
        if capability == "portfolio.get_current_positions":
            data = {"user_id": user_id, "positions": _MOCK_POSITIONS, "is_mock": True}
        return Observation(
            observation_id=str(uuid4()),
            capability=capability,
            status="SUCCESS",
            data=data,
            data_quality=DataQuality(completeness=0.6, quality_status="PARTIAL"),  # mock 数据标记 PARTIAL
            provenance=[ProvenanceRecord(source="mock-java", tool=capability, retrieved_at=_now_iso())],
        )

    @staticmethod
    def _failed_observation(capability: str, message: str) -> Observation:
        return Observation(
            observation_id=str(uuid4()),
            capability=capability,
            status="FAILED",
            data=None,
            data_quality=DataQuality(quality_status="INVALID"),
            provenance=[],
            error_code="JAVA_UNAVAILABLE",
            error_message=message,
        )


# ── mock 持仓数据（确定性，测试用）──
_MOCK_POSITIONS = [
    {"symbol": "600519", "name": "贵州茅台", "quantity": 100, "cost_price": 1500.0, "current_price": None},
    {"symbol": "000001", "name": "平安银行", "quantity": 2000, "cost_price": 10.5, "current_price": None},
]

_MOCK_DATA = {
    "portfolio.get_account_snapshot": {"user_id": "unknown", "total_asset": 0.0, "cash": 0.0, "is_mock": True},
    "portfolio.get_transaction_history": {"transactions": [], "is_mock": True},
    "user.get_risk_profile": {"risk_tolerance": "moderate", "preferred_sectors": [], "forbidden_symbols": [], "is_mock": True},
}


def create_java_adapter(base_url: str | None = None, timeout_seconds: float = 10.0) -> JavaDataAdapter:
    """工厂函数：创建 HttpJavaDataAdapter。

    base_url 来自配置 JAVA_API_BASE_URL；未配置时 Adapter 内部自动 mock 降级。
    """
    return HttpJavaDataAdapter(base_url=base_url, timeout_seconds=timeout_seconds)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
