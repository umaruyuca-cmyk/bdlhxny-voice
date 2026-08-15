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
import time
from typing import Any, Protocol
from uuid import uuid4

from bdlh_runtime.contracts.observation import DataQuality, Observation, ProvenanceRecord

logger = logging.getLogger("bdlh_runtime.tools.java")


class JavaDataAdapter(Protocol):
    """用户持仓、账户和风险偏好必须经由 Java 服务读取。"""

    async def execute(self, capability: str, arguments: dict) -> Observation:
        """调用白名单 Java Data API 并转换为 Observation。"""
        ...


# Java 白名单能力（架构文档 §13.3），Adapter 只允许这些
JAVA_CAPABILITIES = {
    "portfolio.get_current_positions",
    "portfolio.get_account_snapshot",
    "portfolio.get_transaction_history",
    "user.get_risk_profile",
}

# 显式路径映射（审查文档 §5.3：Adapter 不得自行拼接 capability 作为 URL）。
# 路径由与 Java 后端共同确定的 API 契约定义，Java 侧必须有对应 Controller。
_JAVA_API_PATHS: dict[str, str] = {
    "portfolio.get_current_positions": "/api/portfolio/positions",
    "portfolio.get_account_snapshot": "/api/portfolio/account",
    "portfolio.get_transaction_history": "/api/portfolio/transactions",
    "user.get_risk_profile": "/api/user/risk-profile",
}


class HttpJavaDataAdapter:
    """通过 HTTP 调用 Java 用户数据服务的实现。

    降级策略（审查文档 §5.3）：
    - 开发环境（production=False）：Java 服务未配置或调用失败时，降级为
      mock 持仓（带 is_mock 标记），保证开发/测试可跑通完整流程；
    - 生产环境（production=True）：**禁止 mock 降级**——服务不可用时返回
      UNAVAILABLE 状态，宁可如实标记不可用也不伪造持仓结论。
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float = 10.0,
        *,
        production: bool = False,
        token: str | None = None,
    ):
        """base_url 为 Java API 根地址；None 时开发环境走 mock 降级。"""
        self._base_url = base_url
        self._timeout = timeout_seconds
        self._production = production
        self._token = token

    async def execute(self, capability: str, arguments: dict) -> Observation:
        if capability not in JAVA_CAPABILITIES:
            return self._failed_observation(capability, f"Java 白名单外能力: {capability}")

        # Java 服务未配置 → 开发环境 mock 降级，生产环境 UNAVAILABLE
        if not self._base_url:
            if self._production:
                return self._unavailable_observation(capability, "Java 服务未配置，生产环境不允许 mock 降级")
            return self._mock_observation(capability, arguments)

        # 真实调用 Java API（显式路径映射，不拼 capability）
        path = _JAVA_API_PATHS.get(capability)
        if path is None:
            return self._failed_observation(capability, f"Java API 无对应契约路径: {capability}")

        # 服务间令牌证明调用方是 Python Runtime；个人 user_id 已在 Python API
        # 通过用户 JWT 校验，个人 JWT 本身不进入 LangGraph State 或 Java Adapter。
        headers = {"X-Internal-Token": self._token} if self._token else {}
        started = time.monotonic()
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url.rstrip('/')}{path}",
                    params={"user_id": arguments.get("user_id")},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                elapsed_ms = int((time.monotonic() - started) * 1000)
                metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
                query_status = str(metadata.get("query_status", "SUCCESS")).upper()
                if query_status != "SUCCESS":
                    return Observation(
                        observation_id=str(uuid4()),
                        capability=capability,
                        status="PARTIAL",
                        data=data,
                        data_quality=DataQuality(
                            completeness=0.0,
                            quality_status="PARTIAL",
                            known_unavailable=[capability],
                        ),
                        provenance=[ProvenanceRecord(
                            source="java-api",
                            tool=capability,
                            as_of=metadata.get("data_time"),
                            retrieved_at=_now_iso(),
                            elapsed_ms=elapsed_ms,
                        )],
                        error_code=f"JAVA_DATA_{query_status}",
                        error_message=f"Java Data API 查询状态: {query_status}",
                    )
                return Observation(
                    observation_id=str(uuid4()),
                    capability=capability,
                    status="SUCCESS",
                    data=data,
                    data_quality=DataQuality(completeness=1.0, quality_status="OK"),
                    provenance=[ProvenanceRecord(
                        source="java-api",
                        tool=capability,
                        as_of=metadata.get("data_time"),
                        retrieved_at=_now_iso(),
                        elapsed_ms=elapsed_ms,
                    )],
                )
        except Exception as exc:
            logger.warning("Java API 调用失败 (capability=%s): %s", capability, exc)
            # 一旦显式配置真实 Java 地址，401/404/超时都必须如实返回不可用；
            # mock 只允许用于完全未配置 base_url 的本地开发环境。
            return self._unavailable_observation(capability, f"Java API 调用失败: {exc}")

    # ── mock 降级实现（开发环境/测试用，带 is_mock 标记）──

    def _mock_observation(self, capability: str, arguments: dict) -> Observation:
        user_id = arguments.get("user_id") or "unknown"
        data = {
            **_MOCK_DATA.get(capability, {}),
            "user_id": user_id,
            "data_mode": "MOCK",
            "is_mock": True,
        }
        if capability == "portfolio.get_current_positions":
            data["positions"] = _MOCK_POSITIONS
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
            provenance=[ProvenanceRecord(
                source="java-api",
                tool=capability,
                retrieved_at=_now_iso(),
            )],
            error_code="JAVA_UNAVAILABLE",
            error_message=message,
        )

    @staticmethod
    def _unavailable_observation(capability: str, message: str) -> Observation:
        """生产环境服务不可用：UNAVAILABLE 状态，明确无数据。"""
        return Observation(
            observation_id=str(uuid4()),
            capability=capability,
            status="UNAVAILABLE",
            data=None,
            data_quality=DataQuality(quality_status="INVALID", known_unavailable=[capability]),
            provenance=[ProvenanceRecord(
                source="java-api",
                tool=capability,
                retrieved_at=_now_iso(),
            )],
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


def create_java_adapter(
    base_url: str | None = None,
    timeout_seconds: float = 10.0,
    *,
    production: bool = False,
    token: str | None = None,
) -> JavaDataAdapter:
    """工厂函数：创建 HttpJavaDataAdapter。

    base_url 来自配置 JAVA_API_BASE_URL；未配置时开发环境自动 mock 降级，
    生产环境返回 UNAVAILABLE（不伪造持仓）。
    """
    return HttpJavaDataAdapter(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        production=production,
        token=token,
    )


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
