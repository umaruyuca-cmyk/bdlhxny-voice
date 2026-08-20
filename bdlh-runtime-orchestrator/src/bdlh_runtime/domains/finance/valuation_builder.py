"""M3 当前持仓估值的确定性构建。

该模块只消费已经标准化的用户事实和行情 Observation，不访问 Java、MCP、
HTTP、LLM 或系统时钟。它不信任用户事实中可能残留的市值、权重和总资产，
而是以 ``quantity * price`` 重新计算，避免成本价或目标配置被误当成当前状态。
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from bdlh_runtime.contracts.observation import DataQuality, Observation, ProvenanceRecord

from .contracts import FinancialDataMode
from .snapshot_builder import (
    ACCOUNT_CAPABILITY,
    NORMALIZED_USER_DATA_SCHEMA,
    PORTFOLIO_VALUATION_CAPABILITY,
    PORTFOLIO_VALUATION_SCHEMA,
    POSITIONS_CAPABILITY,
)

QUOTE_CAPABILITY = "market.get_realtime_quote"
# PORTFOLIO_VALUATION_CAPABILITY / PORTFOLIO_VALUATION_SCHEMA 的唯一真源在
# snapshot_builder.py（与其它 portfolio 能力常量同处），本模块只导入不重定义，
# 避免字符串双源漂移。


class PortfolioValuationError(ValueError):
    """估值输入不完整或无法验证时的 fail-closed 异常。"""

    code = "PORTFOLIO_VALUATION_BUILD_FAILED"


class PortfolioValuationInput(BaseModel):
    """确定性估值 Capability 的严格输入，禁止传入原始 Java/MCP 载荷。"""

    model_config = ConfigDict(extra="forbid")

    positions_observation: Observation
    account_observation: Observation
    quote_observations: list[Observation] = Field(default_factory=list)
    authenticated_user_id: str = Field(min_length=1)


class PortfolioValuationBuilder:
    """以精确证券身份匹配行情并构建只读当前估值 Observation。"""

    def build(
        self,
        *,
        positions_observation: Observation,
        account_observation: Observation,
        quote_observations: list[Observation],
        authenticated_user_id: str,
    ) -> Observation:
        positions_data = self._user_data(positions_observation, POSITIONS_CAPABILITY)
        account_data = self._user_data(account_observation, ACCOUNT_CAPABILITY)
        user_id = str(authenticated_user_id).strip()
        if not user_id or positions_data.get("user_id") != user_id or account_data.get("user_id") != user_id:
            raise PortfolioValuationError("Portfolio valuation user identity mismatch")

        account = account_data.get("account")
        if not isinstance(account, dict):
            raise PortfolioValuationError("Account observation is missing account data")
        currency = self._identity_part(account.get("currency"), "account currency")
        cash = self._non_negative_number(account.get("cash"), "account cash")

        quotes = self._quotes_by_identity(quote_observations)
        valued_positions: list[dict[str, Any]] = []
        for item in positions_data.get("positions", []):
            if not isinstance(item, dict):
                raise PortfolioValuationError("Position entry must be an object")
            quantity = self._positive_number(item.get("quantity"), "position quantity")
            identity = (
                self._identity_part(item.get("symbol"), "position symbol"),
                self._identity_part(item.get("exchange"), "position exchange"),
                self._identity_part(item.get("currency"), "position currency"),
            )
            if identity[2] != currency:
                raise PortfolioValuationError("Cross-currency portfolio valuation requires an explicit FX capability")
            quote = quotes.get(identity)
            if quote is None:
                raise PortfolioValuationError("Current quote missing for " + ":".join(identity))
            market_value = quantity * quote["price"]
            valued_positions.append(
                {
                    "symbol": identity[0],
                    "name": item.get("name"),
                    "exchange": identity[1],
                    "currency": identity[2],
                    "quantity": quantity,
                    "market_value": market_value,
                    "industry": item.get("industry"),
                    "quote_observation_id": quote["observation_id"],
                    "source": PORTFOLIO_VALUATION_CAPABILITY,
                }
            )

        valued_positions.sort(key=lambda item: (item["symbol"], item["exchange"], item["currency"]))
        invested_value = sum(item["market_value"] for item in valued_positions)
        total_assets = cash + invested_value
        if total_assets <= 0:
            raise PortfolioValuationError("Portfolio total_assets must be positive")
        for item in valued_positions:
            item["weight_pct"] = item["market_value"] / total_assets * 100

        sources = [positions_observation, account_observation, *quote_observations]
        captured_at = self._verified_retrieved_at(sources)
        source_ids = sorted(item.observation_id for item in sources)
        valuation_id = "portfolio-valuation:" + sha256("|".join(source_ids).encode()).hexdigest()[:24]
        return Observation(
            observation_id=valuation_id,
            capability=PORTFOLIO_VALUATION_CAPABILITY,
            status="SUCCESS",
            data={
                "schema_version": PORTFOLIO_VALUATION_SCHEMA,
                "user_id": user_id,
                "data_mode": self._combined_data_mode(positions_data, account_data),
                "currency": currency,
                "positions": valued_positions,
                "account": {
                    "total_assets": total_assets,
                    "cash": cash,
                    "currency": currency,
                    "source": PORTFOLIO_VALUATION_CAPABILITY,
                },
                "source_refs": source_ids,
            },
            data_quality=DataQuality(completeness=1.0, freshness="VERIFIED", quality_status="OK"),
            provenance=[
                ProvenanceRecord(
                    source="deterministic-portfolio-valuation",
                    tool=PORTFOLIO_VALUATION_CAPABILITY,
                    retrieved_at=captured_at.isoformat(),
                    raw_reference="|".join(source_ids),
                )
            ],
        )

    @staticmethod
    def _user_data(observation: Observation, capability: str) -> dict[str, Any]:
        if observation.capability != capability or observation.status not in {"SUCCESS", "PARTIAL"}:
            raise PortfolioValuationError(f"Required user observation unavailable: {capability}")
        if (
            not isinstance(observation.data, dict)
            or observation.data.get("schema_version") != NORMALIZED_USER_DATA_SCHEMA
        ):
            raise PortfolioValuationError(f"Required user observation is not normalized: {capability}")
        if observation.data.get("data_mode") in {FinancialDataMode.MOCK.value, FinancialDataMode.UNAVAILABLE.value}:
            raise PortfolioValuationError(f"Required user observation cannot support valuation: {capability}")
        return observation.data

    def _quotes_by_identity(self, observations: list[Observation]) -> dict[tuple[str, str, str], dict[str, Any]]:
        quotes: dict[tuple[str, str, str], dict[str, Any]] = {}
        for observation in observations:
            if observation.capability != QUOTE_CAPABILITY or observation.status not in {"SUCCESS", "PARTIAL"}:
                raise PortfolioValuationError("Required realtime quote observation unavailable")
            if observation.data_quality.quality_status in {"INVALID", "STALE"}:
                raise PortfolioValuationError("Realtime quote is stale or invalid")
            if not isinstance(observation.data, dict):
                raise PortfolioValuationError("Realtime quote must be a structured object")
            data = observation.data
            identity = (
                self._identity_part(data.get("symbol"), "quote symbol"),
                self._identity_part(data.get("exchange"), "quote exchange"),
                self._identity_part(data.get("currency"), "quote currency"),
            )
            if not data.get("as_of"):
                raise PortfolioValuationError("Realtime quote requires verifiable as_of")
            self._verified_retrieved_at([observation])
            if identity in quotes:
                raise PortfolioValuationError("Duplicate quote identity: " + ":".join(identity))
            quotes[identity] = {
                "price": self._positive_number(data.get("price"), "quote price"),
                "observation_id": observation.observation_id,
            }
        return quotes

    @staticmethod
    def _combined_data_mode(*observations: dict[str, Any]) -> str:
        modes = {item.get("data_mode") for item in observations}
        if FinancialDataMode.TEST_FIXTURE.value in modes:
            return FinancialDataMode.TEST_FIXTURE.value
        if modes == {FinancialDataMode.USER_CONFIRMED.value}:
            return FinancialDataMode.USER_CONFIRMED.value
        return FinancialDataMode.LIVE.value

    @staticmethod
    def _identity_part(value: Any, label: str) -> str:
        normalized = str(value or "").strip().upper()
        if not normalized:
            raise PortfolioValuationError(f"Missing {label}")
        return normalized

    @staticmethod
    def _positive_number(value: Any, label: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise PortfolioValuationError(f"Missing or invalid {label}") from exc
        if number <= 0:
            raise PortfolioValuationError(f"{label} must be positive")
        return number

    @staticmethod
    def _non_negative_number(value: Any, label: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise PortfolioValuationError(f"Missing or invalid {label}") from exc
        if number < 0:
            raise PortfolioValuationError(f"{label} must be non-negative")
        return number

    @staticmethod
    def _verified_retrieved_at(observations: list[Observation]) -> datetime:
        values: list[datetime] = []
        for observation in observations:
            if not observation.provenance:
                raise PortfolioValuationError("Observation requires verifiable retrieved_at provenance")
            for provenance in observation.provenance:
                try:
                    parsed = datetime.fromisoformat(provenance.retrieved_at.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise PortfolioValuationError("Observation has invalid retrieved_at provenance") from exc
                values.append(parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC))
        if not values:
            raise PortfolioValuationError("Observation requires verifiable retrieved_at provenance")
        return max(values)
