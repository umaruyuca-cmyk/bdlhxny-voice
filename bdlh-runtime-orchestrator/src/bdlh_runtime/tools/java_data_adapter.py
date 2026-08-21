"""Java 用户数据 API 适配器。

用户持仓、账户和风险偏好必须经由 Java 服务读取（架构文档 §13.3）：
Python 不允许绕过 Java API 直接读取用户业务表。

设计原则（与 MCP adapter 一致）：
- 统一能力 → Java HTTP API 的翻译在 Adapter 内完成；
- Java 返回结果转换为 Observation，不允许 Graph 节点直接拼接 Java JSON；
- **禁止 mock 降级**（G3）：未配置或调用失败一律返回 UNAVAILABLE，不伪造持仓结论。
"""

from __future__ import annotations

import logging
import time
from datetime import UTC
from typing import Protocol
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
_JAVA_API_PATHS: dict[str, str] = {
    "portfolio.get_current_positions": "/api/portfolio/positions",
    "portfolio.get_account_snapshot": "/api/portfolio/account",
    "portfolio.get_transaction_history": "/api/portfolio/transactions",
    "user.get_risk_profile": "/api/user/risk-profile",
}


class HttpJavaDataAdapter:
    """通过 HTTP 调用 Java 用户数据服务的实现。

    服务未配置或调用失败时返回 UNAVAILABLE，永不 mock（实施 Prompt 缺口 G3）。
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float = 10.0,
        *,
        token: str | None = None,
    ):
        self._base_url = base_url
        self._timeout = timeout_seconds
        self._token = token

    async def execute(self, capability: str, arguments: dict) -> Observation:
        if capability not in JAVA_CAPABILITIES:
            return self._failed_observation(capability, f"Java 白名单外能力: {capability}")

        if not self._base_url:
            return self._unavailable_observation(capability, "Java 服务未配置，不允许 mock 降级")

        path = _JAVA_API_PATHS.get(capability)
        if path is None:
            return self._failed_observation(capability, f"Java API 无对应契约路径: {capability}")

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
                        provenance=[
                            ProvenanceRecord(
                                source="java-api",
                                tool=capability,
                                as_of=metadata.get("data_time"),
                                retrieved_at=_now_iso(),
                                elapsed_ms=elapsed_ms,
                            )
                        ],
                        error_code=f"JAVA_DATA_{query_status}",
                        error_message=f"Java Data API 查询状态: {query_status}",
                    )
                return Observation(
                    observation_id=str(uuid4()),
                    capability=capability,
                    status="SUCCESS",
                    data=data,
                    data_quality=DataQuality(completeness=1.0, quality_status="OK"),
                    provenance=[
                        ProvenanceRecord(
                            source="java-api",
                            tool=capability,
                            as_of=metadata.get("data_time"),
                            retrieved_at=_now_iso(),
                            elapsed_ms=elapsed_ms,
                        )
                    ],
                )
        except Exception as exc:
            logger.warning("Java API 调用失败 (capability=%s): %s", capability, exc)
            return self._unavailable_observation(capability, f"Java API 调用失败: {exc}")

    @staticmethod
    def _failed_observation(capability: str, message: str) -> Observation:
        return Observation(
            observation_id=str(uuid4()),
            capability=capability,
            status="FAILED",
            data=None,
            data_quality=DataQuality(quality_status="INVALID"),
            provenance=[
                ProvenanceRecord(
                    source="java-api",
                    tool=capability,
                    retrieved_at=_now_iso(),
                )
            ],
            error_code="JAVA_UNAVAILABLE",
            error_message=message,
        )

    @staticmethod
    def _unavailable_observation(capability: str, message: str) -> Observation:
        return Observation(
            observation_id=str(uuid4()),
            capability=capability,
            status="UNAVAILABLE",
            data=None,
            data_quality=DataQuality(quality_status="INVALID", known_unavailable=[capability]),
            provenance=[
                ProvenanceRecord(
                    source="java-api",
                    tool=capability,
                    retrieved_at=_now_iso(),
                )
            ],
            error_code="JAVA_UNAVAILABLE",
            error_message=message,
        )


def create_java_adapter(
    base_url: str | None = None,
    timeout_seconds: float = 10.0,
    *,
    token: str | None = None,
    production: bool | None = None,
) -> JavaDataAdapter:
    """工厂函数：创建 HttpJavaDataAdapter。

    ``production`` 参数已废弃（G3）；保留仅为兼容旧调用方，行为始终 fail-closed。
    """
    del production
    return HttpJavaDataAdapter(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        token=token,
    )


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()
