"""M3 用户金融快照的标准化与 fail-closed 确定性构建。

本模块不依赖 Java DTO、HTTP、LangGraph、LLM 或当前时间。当前权威数据字段不足时，
只构建 PARTIAL/LIMITED Snapshot，不用成本价、目标权重或默认阈值伪造用户状态。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from bdlh_runtime.contracts.observation import Observation

from .contracts import (
    AccountSnapshot,
    FinancialDataMode,
    FinancialDataReference,
    FinancialDomainRequest,
    FinancialGoal,
    FinancialSnapshot,
    LiquiditySnapshot,
    PortfolioPosition,
    RiskProfile,
)

POSITIONS_CAPABILITY = "portfolio.get_current_positions"
ACCOUNT_CAPABILITY = "portfolio.get_account_snapshot"
RISK_PROFILE_CAPABILITY = "user.get_risk_profile"
USER_SNAPSHOT_CAPABILITIES = frozenset(
    {
        POSITIONS_CAPABILITY,
        ACCOUNT_CAPABILITY,
        RISK_PROFILE_CAPABILITY,
    }
)
NORMALIZED_USER_DATA_SCHEMA = "financial-user-observation.v1"
PORTFOLIO_VALUATION_CAPABILITY = "portfolio.build_current_valuation"
PORTFOLIO_VALUATION_SCHEMA = "portfolio-valuation.v1"

ExecutionEnvironment = Literal["production", "development"]


class FinancialSnapshotError(ValueError):
    """带稳定公开错误码的 Snapshot 基础异常。"""

    code = "FINANCIAL_SNAPSHOT_BUILD_FAILED"


class SnapshotIdentityError(FinancialSnapshotError):
    """Java 用户身份缺失或与认证上下文不一致。"""

    code = "SNAPSHOT_IDENTITY_MISMATCH"


class UserFinancialObservationNormalizer:
    """把精确用户 Capability 响应裁剪为供应商无关的稳定业务 Observation。"""

    def normalize(
        self,
        observation: Observation,
        *,
        authenticated_user_id: str,
    ) -> Observation:
        if observation.capability not in USER_SNAPSHOT_CAPABILITIES:
            raise FinancialSnapshotError(f"Unsupported financial snapshot capability: {observation.capability}")
        if observation.status in {"FAILED", "UNAVAILABLE"}:
            return observation.model_copy(deep=True)
        if not isinstance(observation.data, dict):
            raise FinancialSnapshotError(f"{observation.capability} must return an object payload")

        raw = observation.data
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        raw_user_id = metadata.get("user_id", raw.get("user_id"))
        expected = self._canonical_user_id(authenticated_user_id)
        actual = self._canonical_user_id(raw_user_id)
        if not actual or actual != expected:
            raise SnapshotIdentityError(f"Snapshot user identity mismatch for {observation.capability}")

        data_mode = self._data_mode(observation)
        confirmation_ref = metadata.get("confirmation_ref", raw.get("confirmation_ref"))
        if data_mode == FinancialDataMode.USER_CONFIRMED and (
            not observation.provenance or not confirmation_ref or not metadata.get("data_time")
        ):
            raise FinancialSnapshotError("USER_CONFIRMED data requires controlled confirmation provenance")

        common: dict[str, Any] = {
            "schema_version": NORMALIZED_USER_DATA_SCHEMA,
            "user_id": actual,
            "data_mode": data_mode.value,
            "is_mock": data_mode == FinancialDataMode.MOCK,
            "source_ref": observation.observation_id,
            "source_type": metadata.get("source_type"),
            "query_status": metadata.get("query_status"),
            "data_time": metadata.get("data_time"),
            "queried_at": metadata.get("queried_at"),
            "profile_version": raw.get("profile_version"),
            "missing_fields": sorted(set(metadata.get("missing_fields") or [])),
        }
        if confirmation_ref:
            common["confirmation_ref"] = str(confirmation_ref)

        if observation.capability == POSITIONS_CAPABILITY:
            common["positions"] = [
                self._position(item, observation.observation_id)
                for item in raw.get("positions", [])
                if isinstance(item, dict)
            ]
        elif observation.capability == ACCOUNT_CAPABILITY:
            common["account"] = {
                "total_assets": raw.get("total_assets", raw.get("total_asset")),
                "cash": raw.get("cash"),
                "currency": raw.get("currency") or "CNY",
                "source": observation.observation_id,
            }
            common["liquidity"] = {
                "liquid_assets": raw.get("liquid_assets"),
                "near_term_cash_needs": raw.get("near_term_cash_needs"),
                "near_term_cash_needs_horizon_days": raw.get("near_term_cash_needs_horizon_days"),
                "currency": raw.get("currency"),
                "source": observation.observation_id,
            }
        else:
            common["risk_profile"] = {
                "risk_level": self._risk_level(raw.get("risk_level", raw.get("risk_tolerance"))),
                "max_loss_tolerance_pct": raw.get("max_loss_tolerance_pct"),
                "source": observation.observation_id,
            }

        return observation.model_copy(update={"data": common}, deep=True)

    @staticmethod
    def _position(item: dict[str, Any], source_ref: str) -> dict[str, Any]:
        # target_weight 与 cost_price 不是当前实际权重/市值，故意不做别名映射。
        symbol = str(item.get("symbol", item.get("code", ""))).strip()
        exchange = item.get("exchange")
        if not (isinstance(exchange, str) and exchange.strip()):
            exchange = UserFinancialObservationNormalizer._infer_cn_exchange(symbol)
        elif isinstance(exchange, str):
            exchange = exchange.strip()
        currency = item.get("currency")
        if not currency and exchange in {"SSE", "SZSE"}:
            currency = "CNY"
        return {
            "symbol": symbol,
            "name": item.get("name"),
            "exchange": exchange,
            "currency": currency,
            "quantity": item.get("quantity", item.get("shares")),
            "market_value": item.get("market_value"),
            "weight_pct": item.get("weight_pct"),
            "industry": item.get("industry", item.get("sector")),
            "source": source_ref,
        }

    @staticmethod
    def _infer_cn_exchange(symbol: str) -> str | None:
        code = symbol.strip()
        if len(code) != 6 or not code.isdigit():
            return None
        if code.startswith(("5", "6", "9")):
            return "SSE"
        if code.startswith(("0", "1", "3")):
            return "SZSE"
        return None

    @staticmethod
    def _risk_level(value: Any) -> str | None:
        normalized = str(value or "").strip().lower()
        return {
            "conservative": "CONSERVATIVE",
            "moderate": "BALANCED",
            "balanced": "BALANCED",
            "aggressive": "AGGRESSIVE",
        }.get(normalized)

    @staticmethod
    def _canonical_user_id(value: Any) -> str:
        return str(value).strip() if value is not None else ""

    @staticmethod
    def _data_mode(observation: Observation) -> FinancialDataMode:
        assert isinstance(observation.data, dict)
        raw = observation.data
        if raw.get("is_mock") is True:
            return FinancialDataMode.MOCK
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        explicit = str(metadata.get("data_mode", raw.get("data_mode", ""))).upper()
        if explicit in {item.value for item in FinancialDataMode}:
            return FinancialDataMode(explicit)
        sources = {item.source.lower() for item in observation.provenance}
        if any("mock" in source for source in sources):
            return FinancialDataMode.MOCK
        if any("fixture" in source for source in sources):
            return FinancialDataMode.TEST_FIXTURE
        if any("confirm" in source for source in sources):
            return FinancialDataMode.USER_CONFIRMED
        if any(source == "java-api" for source in sources):
            # Java HTTP 查询成功只表示传输成功；缺少 v2 真实性元数据时不得提升为 LIVE。
            return FinancialDataMode.UNAVAILABLE
        return FinancialDataMode.LIVE


class FinancialSnapshotBuilder:
    """从标准用户 Observations 构建可追溯 Snapshot；无 I/O、无隐式时钟。"""

    def build(
        self,
        *,
        request: FinancialDomainRequest,
        observations: list[Observation],
        execution_environment: ExecutionEnvironment,
    ) -> FinancialSnapshot:
        if not request.requires_financial_snapshot:
            raise FinancialSnapshotError("FinancialSnapshotBuilder only accepts requires_financial_snapshot requests")
        if execution_environment not in {"production", "development"}:
            raise FinancialSnapshotError("Unsupported execution environment")

        by_capability: dict[str, Observation] = {}
        valuation_observation: Observation | None = None
        for observation in observations:
            if observation.capability == PORTFOLIO_VALUATION_CAPABILITY:
                if valuation_observation is not None:
                    raise FinancialSnapshotError("Duplicate portfolio valuation observation")
                valuation_observation = observation
                continue
            if observation.capability not in USER_SNAPSHOT_CAPABILITIES:
                continue
            if observation.capability in by_capability:
                raise FinancialSnapshotError(f"Duplicate snapshot capability: {observation.capability}")
            by_capability[observation.capability] = observation

        captured_at = self._captured_at(observations)
        usable = {
            capability: observation
            for capability, observation in by_capability.items()
            if observation.status in {"SUCCESS", "PARTIAL"}
            and isinstance(observation.data, dict)
            and observation.data.get("schema_version") == NORMALIZED_USER_DATA_SCHEMA
            and observation.data.get("data_mode") != FinancialDataMode.UNAVAILABLE.value
            and observation.data_quality.quality_status != "INVALID"
        }
        for observation in usable.values():
            if str(observation.data.get("user_id", "")).strip() != request.authenticated_user_id.strip():
                raise SnapshotIdentityError(f"Normalized snapshot identity mismatch for {observation.capability}")

        modes = {FinancialDataMode(str(item.data["data_mode"])) for item in usable.values()}
        data_mode = self._combined_mode(modes, has_usable=bool(usable))
        data_references = [
            FinancialDataReference(
                capability=capability,
                observation_id=observation.observation_id,
                data_mode=FinancialDataMode(str(observation.data["data_mode"])),
                source_type=observation.data.get("source_type"),
                data_time=observation.data.get("data_time"),
                queried_at=observation.data.get("queried_at"),
                confirmation_ref=observation.data.get("confirmation_ref"),
                profile_version=observation.data.get("profile_version"),
            )
            for capability, observation in sorted(usable.items())
        ]
        limitations: list[str] = []
        missing_capabilities = sorted(USER_SNAPSHOT_CAPABILITIES - set(usable))
        limitations.extend(f"Required user capability unavailable: {name}" for name in missing_capabilities)
        limitations.extend(
            f"Partial user capability: {item.capability}" for item in usable.values() if item.status == "PARTIAL"
        )

        positions: list[PortfolioPosition] = []
        positions_observation = usable.get(POSITIONS_CAPABILITY)
        if positions_observation is not None:
            positions = [
                PortfolioPosition.model_validate(
                    {
                        **item,
                        # 只能由本地估值器写入当前市值与权重；用户事实中的旧字段不可信。
                        "market_value": None,
                        "weight_pct": None,
                    }
                )
                for item in positions_observation.data.get("positions", [])
            ]

        account = None
        liquidity = None
        account_observation = usable.get(ACCOUNT_CAPABILITY)
        if account_observation is not None:
            account = AccountSnapshot.model_validate(
                {
                    **account_observation.data.get("account", {}),
                    # 同上：Java 用户事实中的账户总额不是本轮当前估值。
                    "total_assets": None,
                }
            )
            liquidity_data = account_observation.data.get("liquidity", {})
            liquidity = LiquiditySnapshot(
                status=(
                    "OK"
                    if liquidity_data.get("liquid_assets") is not None
                    and liquidity_data.get("near_term_cash_needs") is not None
                    and liquidity_data.get("near_term_cash_needs_horizon_days") is not None
                    and liquidity_data.get("currency")
                    else "UNKNOWN"
                ),
                liquid_assets=liquidity_data.get("liquid_assets"),
                near_term_cash_needs=liquidity_data.get("near_term_cash_needs"),
                near_term_cash_needs_horizon_days=liquidity_data.get("near_term_cash_needs_horizon_days"),
                currency=liquidity_data.get("currency"),
                source=liquidity_data.get("source"),
            )
            if (
                liquidity.liquid_assets is None
                or liquidity.near_term_cash_needs is None
                or liquidity.near_term_cash_needs_horizon_days is None
                or liquidity.currency is None
            ):
                liquidity.limitations.append("Liquidity critical fields missing")
                limitations.append("Liquidity critical fields missing")

        valuation = self._usable_valuation(
            valuation_observation,
            request.authenticated_user_id,
        )
        if valuation is None:
            if positions_observation is not None and account_observation is not None:
                limitations.append("Current portfolio valuation unavailable; concentration unavailable")
                limitations.append("Current portfolio valuation unavailable; account total_assets unavailable")
        else:
            valuation_positions = valuation["positions"]
            positions = [
                PortfolioPosition.model_validate(
                    {key: value for key, value in item.items() if key != "quote_observation_id"}
                )
                for item in valuation_positions
            ]
            account = AccountSnapshot.model_validate(valuation["account"])

        risk_profile = None
        risk_observation = usable.get(RISK_PROFILE_CAPABILITY)
        if risk_observation is not None:
            risk_profile = RiskProfile.model_validate(risk_observation.data.get("risk_profile", {}))
            if risk_profile.risk_level is None:
                limitations.append("Risk profile risk_level missing")
            if risk_profile.max_loss_tolerance_pct is None:
                limitations.append("Risk profile max_loss_tolerance_pct missing")

        profile_versions = {
            item.profile_version
            for item in data_references
            if item.capability in {ACCOUNT_CAPABILITY, RISK_PROFILE_CAPABILITY} and item.profile_version is not None
        }
        if len(profile_versions) > 1:
            limitations.append("Account and risk profile versions are inconsistent")

        goals: list[FinancialGoal] = []
        for item in request.goals:
            if item.source in {
                "USER_EXPLICIT",
                "PROFILE_CONFIRMED",
                "MEMORY_CONFIRMED",
            }:
                goals.append(
                    FinancialGoal(
                        goal_id=item.goal_id,
                        description=item.description,
                        horizon=item.horizon,
                        target_date=item.target_date,
                        target_amount=item.target_amount,
                        source=item.source,
                    )
                )
            else:
                limitations.append(f"Unconfirmed goal excluded from suitability rules: {item.goal_id}")

        if data_mode == FinancialDataMode.MOCK:
            limitations.append("MOCK user data cannot support personalization")
        if data_mode == FinancialDataMode.TEST_FIXTURE:
            limitations.append("TEST_FIXTURE user data is forbidden in product paths")

        critical_missing = bool(limitations)
        if missing_capabilities or not usable:
            completeness = "LIMITED"
        elif critical_missing:
            completeness = "PARTIAL"
        else:
            completeness = "COMPLETE"
        if data_mode in {
            FinancialDataMode.MOCK,
            FinancialDataMode.UNAVAILABLE,
            FinancialDataMode.TEST_FIXTURE,
        }:
            completeness = "LIMITED"

        return FinancialSnapshot(
            user_id=request.authenticated_user_id,
            captured_at=captured_at,
            data_mode=data_mode,
            is_mock=data_mode == FinancialDataMode.MOCK,
            provenance=[
                item.observation_id
                for item in sorted(observations, key=lambda value: value.observation_id)
                if item.capability in USER_SNAPSHOT_CAPABILITIES or item.capability == PORTFOLIO_VALUATION_CAPABILITY
            ],
            data_references=data_references,
            positions=positions,
            account=account,
            risk_profile=risk_profile,
            goals=goals,
            liquidity=liquidity,
            proposed_amount=request.proposed_amount,
            proposed_weight_pct=request.proposed_weight_pct,
            completeness=completeness,
            limitations=list(dict.fromkeys(limitations)),
        )

    @staticmethod
    def _captured_at(observations: list[Observation]) -> datetime:
        values: list[datetime] = []
        for observation in observations:
            if observation.capability not in USER_SNAPSHOT_CAPABILITIES | {PORTFOLIO_VALUATION_CAPABILITY}:
                continue
            for provenance in observation.provenance:
                try:
                    parsed = datetime.fromisoformat(provenance.retrieved_at.replace("Z", "+00:00"))
                except ValueError:
                    continue
                values.append(parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC))
        if not values:
            raise FinancialSnapshotError("Snapshot observations require verifiable retrieved_at provenance")
        return max(values)

    @staticmethod
    def _usable_valuation(
        observation: Observation | None,
        authenticated_user_id: str,
    ) -> dict[str, Any] | None:
        if observation is None:
            return None
        if observation.status not in {"SUCCESS", "PARTIAL"} or not isinstance(observation.data, dict):
            return None
        data = observation.data
        if data.get("schema_version") != PORTFOLIO_VALUATION_SCHEMA:
            return None
        if str(data.get("user_id", "")).strip() != authenticated_user_id.strip():
            raise SnapshotIdentityError("Portfolio valuation user identity mismatch")
        if observation.data_quality.quality_status in {"INVALID", "STALE"}:
            return None
        if not isinstance(data.get("positions"), list) or not isinstance(data.get("account"), dict):
            return None
        return data

    @staticmethod
    def _combined_mode(
        modes: set[FinancialDataMode],
        *,
        has_usable: bool,
    ) -> FinancialDataMode:
        if FinancialDataMode.MOCK in modes:
            return FinancialDataMode.MOCK
        if FinancialDataMode.TEST_FIXTURE in modes:
            return FinancialDataMode.TEST_FIXTURE
        if not has_usable:
            return FinancialDataMode.UNAVAILABLE
        if modes == {FinancialDataMode.USER_CONFIRMED}:
            return FinancialDataMode.USER_CONFIRMED
        return FinancialDataMode.LIVE
