"""金融领域边界契约（31 号统一开发实施 Prompt §7.3-§7.5、§9.2、§10.3）。

契约由 M1 ``FinanceRuntime`` 消费；当前只开放客观股票研究，Suitability 等
个性化动作保持禁用并返回稳定错误。

契约原则（对齐通用层 ``domains/contracts.py``）：
- ``FinancialDomainRequest`` 扩展 ``DomainRequest``，禁止复制一套语义相同的基类；
- ``FinancialDomainOutcome`` 扩展 ``DomainOutcome``，领域结果用显式强类型字段；
- ``EvidenceFact / Finding`` 扩展通用 ``DomainFact / DomainFinding``，
  不得重新定义语义冲突的同名字段；
- 所有结果必须携带证据引用与限制，数据缺失用 ``quality / completeness /
  limitations`` 如实标记，不伪造成功数据；
- 客观研究（``StockResearchResult``）不输出个性化结论；个性化结论只能由
  Suitability 层结合用户状态产生（§5.3 客观研究与用户适配分离）。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from bdlh_runtime.contracts.analysis import AnalysisResult
from bdlh_runtime.domains.contracts import (
    ConfidenceAssessment,
    DomainConflict,
    DomainContractModel,
    DomainFact,
    DomainFinding,
    DomainOutcome,
    DomainRequest,
    DomainRisk,
)


# ── 请求边界 ───────────────────────────────────────────────────────────────


class FinancialIntent(StrEnum):
    """用户本轮金融意图（阶段 2 Finance Runtime 据此选择执行链）。"""

    STOCK_RESEARCH = "STOCK_RESEARCH"
    SUITABILITY = "SUITABILITY"
    PORTFOLIO_IMPACT = "PORTFOLIO_IMPACT"
    GOAL_PLANNING = "GOAL_PLANNING"


class FinancialInstrument(DomainContractModel):
    """金融实体引用。"""

    symbol: str
    name: str | None = None
    instrument_type: Literal["stock", "etf", "index", "fund", "bond"] = "stock"
    market: str = "CN"


class InstrumentMention(DomainContractModel):
    """Cognitive 提取、由 Finance 解析的证券提及。"""

    raw_text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    mention_type: Literal["CODE", "NAME", "ALIAS", "REFERENCE"]
    market_hint: str | None = None
    exchange_hint: str | None = None
    context_entity_ref: str | None = None


class InstrumentCandidate(DomainContractModel):
    """带来源的受控证券主数据候选。"""

    instrument: FinancialInstrument
    canonical_symbol: str = Field(min_length=1)
    exchange: str = Field(min_length=1)
    currency: str | None = None
    match_type: Literal["EXACT_CODE", "EXACT_NAME", "EXACT_ALIAS", "FUZZY"]
    source_refs: list[str] = Field(min_length=1)


class InstrumentResolutionRequest(DomainRequest):
    """Finance 的预研究解析请求；不是新的金融业务意图或隐藏工具调用。"""

    domain: Literal["finance"] = "finance"
    mention: InstrumentMention
    allowed_instrument_types: set[Literal["stock", "etf", "index", "fund", "bond"]] = Field(
        default_factory=lambda: {"stock"}
    )
    max_candidates: int = Field(default=5, ge=1, le=5)


class InstrumentResolutionOutcome(DomainOutcome):
    """证券解析的结构化结果；Cognitive 仅按该状态路由。"""

    domain: Literal["finance"] = "finance"
    resolution_status: Literal["RESOLVED", "AMBIGUOUS", "NOT_FOUND", "UNAVAILABLE"]
    selected: InstrumentCandidate | None = None
    candidates: list[InstrumentCandidate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_resolution(self) -> "InstrumentResolutionOutcome":
        if self.resolution_status == "RESOLVED" and self.selected is None:
            raise ValueError("RESOLVED requires a selected candidate")
        if self.resolution_status != "RESOLVED" and self.selected is not None:
            raise ValueError("only RESOLVED may carry a selected candidate")
        if self.resolution_status == "AMBIGUOUS" and not self.candidates:
            raise ValueError("AMBIGUOUS requires at least one candidate")
        return self


class FinancialDomainRequest(DomainRequest):
    """一次金融领域调用的输入边界。"""

    domain: Literal["finance"] = "finance"
    financial_intent: FinancialIntent = FinancialIntent.STOCK_RESEARCH
    requested_topics: set[Literal[
        "news",
        "money_flow",
        "industry",
        "web_research",
    ]] = Field(default_factory=set)
    instruments: list[FinancialInstrument] = Field(default_factory=list)
    requires_financial_snapshot: bool = False

    @model_validator(mode="after")
    def validate_finance_request(self) -> "FinancialDomainRequest":
        # 重写 §6.2：允许多标的对比（instruments >= 1）；每个涉及标的的 Goal
        # 必须最终有已解析 instrument（运行时由 resolve 闭包保证）。
        if self.financial_intent in {FinancialIntent.STOCK_RESEARCH, FinancialIntent.SUITABILITY} and not self.instruments:
            raise ValueError(f"{self.financial_intent} requires at least one instrument")
        return self


# ── 最小金融快照（M3 SuitabilityEngine 输入，数据缺失如实标记） ──────────


class PortfolioPosition(DomainContractModel):
    """用户当前持仓条目。"""

    symbol: str = Field(min_length=1)
    name: str | None = None
    exchange: str | None = None
    currency: str | None = None
    quantity: float | None = Field(default=None, ge=0)
    market_value: float | None = Field(default=None, ge=0)
    weight_pct: float | None = Field(default=None, ge=0, le=100)
    industry: str | None = None
    source: str


class AccountSnapshot(DomainContractModel):
    """账户级快照。"""

    total_assets: float | None = Field(default=None, ge=0)
    cash: float | None = Field(default=None, ge=0)
    currency: str = Field(default="CNY", min_length=3)
    source: str


class RiskProfile(DomainContractModel):
    """用户风险画像；缺失字段为 None 时视为信息不足。"""

    risk_level: Literal["CONSERVATIVE", "BALANCED", "AGGRESSIVE"] | None = None
    max_loss_tolerance_pct: float | None = Field(default=None, ge=0, le=100)
    source: str


class FinancialDataReference(DomainContractModel):
    """一个用户数据块的真实性、版本和时效引用。

    Engine 只能通过该结构验证受控确认与 freshness，不能把普通 observation id
    当作用户确认凭证。``profile_version`` 对暂未提供版本号的持仓接口允许为空。
    """

    capability: Literal[
        "portfolio.get_current_positions",
        "portfolio.get_account_snapshot",
        "user.get_risk_profile",
    ]
    observation_id: str = Field(min_length=1)
    data_mode: "FinancialDataMode"
    source_type: str | None = None
    data_time: datetime | None = None
    queried_at: datetime | None = None
    confirmation_ref: str | None = None
    profile_version: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_controlled_confirmation(self) -> "FinancialDataReference":
        if self.data_mode == FinancialDataMode.USER_CONFIRMED:
            if not self.confirmation_ref or self.data_time is None:
                raise ValueError(
                    "USER_CONFIRMED data references require confirmation_ref and data_time"
                )
        return self


class FinancialGoal(DomainContractModel):
    """用户财务目标；来源优先级见 31 号 §10.2。"""

    goal_id: str
    description: str
    horizon: Literal["SHORT_TERM", "MEDIUM_TERM", "LONG_TERM"] | None = None
    target_date: datetime | None = None
    target_amount: float | None = None
    source: Literal["USER_EXPLICIT", "PROFILE_CONFIRMED", "MEMORY_CONFIRMED", "TASK", "INFERRED"]


class LiquiditySnapshot(DomainContractModel):
    """流动性快照；``status`` 与 Suitability 的 ``LiquidityImpact`` 语义不同。"""

    status: Literal["OK", "CONSTRAINED", "UNKNOWN"] = "UNKNOWN"
    liquid_assets: float | None = Field(default=None, ge=0)
    near_term_cash_needs: float | None = Field(default=None, ge=0)
    near_term_cash_needs_horizon_days: int | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3)
    source: str | None = None
    limitations: list[str] = Field(default_factory=list)


class FinancialDataMode(StrEnum):
    """金融快照真实性；MOCK/UNAVAILABLE 不得驱动真实个性化结论。"""

    LIVE = "LIVE"
    USER_CONFIRMED = "USER_CONFIRMED"
    TEST_FIXTURE = "TEST_FIXTURE"
    MOCK = "MOCK"
    UNAVAILABLE = "UNAVAILABLE"


class FinancialSnapshot(DomainContractModel):
    """用户当前金融状态的只读快照。

    只读取本轮目标所需的最小字段；缺失数据用 ``completeness`` 和
    ``limitations`` 如实标记，禁止用默认值伪造用户状态。
    """

    user_id: str
    captured_at: datetime
    data_mode: FinancialDataMode = FinancialDataMode.UNAVAILABLE
    is_mock: bool = False
    provenance: list[str] = Field(default_factory=list)
    data_references: list[FinancialDataReference] = Field(default_factory=list)
    positions: list[PortfolioPosition] = Field(default_factory=list)
    account: AccountSnapshot | None = None
    risk_profile: RiskProfile | None = None
    goals: list[FinancialGoal] = Field(default_factory=list)
    liquidity: LiquiditySnapshot | None = None
    completeness: Literal["COMPLETE", "PARTIAL", "LIMITED", "UNKNOWN"] = "UNKNOWN"
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_data_mode(self) -> "FinancialSnapshot":
        if self.data_mode == FinancialDataMode.MOCK and not self.is_mock:
            raise ValueError("MOCK financial snapshots must set is_mock=true")
        if self.is_mock and self.data_mode != FinancialDataMode.MOCK:
            raise ValueError("is_mock=true requires data_mode=MOCK")
        if self.data_mode == FinancialDataMode.USER_CONFIRMED and not self.provenance:
            raise ValueError("USER_CONFIRMED snapshots require confirmation provenance")
        capabilities = [item.capability for item in self.data_references]
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("FinancialSnapshot data_references must be unique by capability")
        if self.data_mode == FinancialDataMode.USER_CONFIRMED:
            if not self.data_references or any(
                item.data_mode != FinancialDataMode.USER_CONFIRMED
                for item in self.data_references
            ):
                raise ValueError(
                    "USER_CONFIRMED snapshots require controlled references for every data block"
                )
        return self


# ── 证据与结论（扩展通用契约，§7.4-§7.5） ─────────────────────────────────


class EvidenceFact(DomainFact):
    """带来源时间与质量的金融事实；第一阶段用 directness + quality 表达。"""

    source: str
    source_time: datetime | None = None
    retrieved_at: datetime
    quality: Literal["HIGH", "MEDIUM", "LOW", "INVALID"] = "MEDIUM"


class Finding(DomainFinding):
    """金融结论；可信度由策略计算，禁止让 LLM 自由输出百分比。"""

    invalidation_conditions: list[str] = Field(default_factory=list)


class EvidenceConflict(DomainConflict):
    """两条证据/结论之间的冲突，保留证据引用，不得静默隐藏。"""

    evidence_refs: list[str] = Field(default_factory=list)


# ── 股票客观研究结果（§9.2；只描述资产本身，不描述用户适配性） ────────────


class MarketSnapshot(DomainContractModel):
    symbol: str
    name: str | None = None
    price: float | None = None
    currency: str = "CNY"
    trade_date: datetime | None = None
    source_time: datetime | None = None
    quality: Literal["HIGH", "MEDIUM", "LOW", "INVALID"] = "MEDIUM"


class Fundamentals(DomainContractModel):
    revenue: float | None = None
    net_profit: float | None = None
    revenue_yoy: float | None = None
    net_profit_yoy: float | None = None
    roe: float | None = None
    debt_ratio: float | None = None
    quality: Literal["HIGH", "MEDIUM", "LOW", "INVALID"] = "MEDIUM"
    limitations: list[str] = Field(default_factory=list)


class Valuation(DomainContractModel):
    pe: float | None = None
    pb: float | None = None
    ps: float | None = None
    method: str | None = None
    quality: Literal["HIGH", "MEDIUM", "LOW", "INVALID"] = "MEDIUM"
    limitations: list[str] = Field(default_factory=list)


class Technicals(DomainContractModel):
    trend: Literal["UP", "DOWN", "SIDEWAYS", "UNKNOWN"] = "UNKNOWN"
    # 保留 AnalysisResult 的确定性计算结构（如 MACD 子字段），不在 Builder 重算。
    indicators: dict[str, JsonValue] = Field(default_factory=dict)
    quality: Literal["HIGH", "MEDIUM", "LOW", "INVALID"] = "MEDIUM"
    limitations: list[str] = Field(default_factory=list)


class MoneyFlow(DomainContractModel):
    net_inflow: float | None = None
    quality: Literal["HIGH", "MEDIUM", "LOW", "INVALID"] = "MEDIUM"
    limitations: list[str] = Field(default_factory=list)


class IndustryContext(DomainContractModel):
    industry: str | None = None
    peers: list[str] = Field(default_factory=list)
    quality: Literal["HIGH", "MEDIUM", "LOW", "INVALID"] = "MEDIUM"
    limitations: list[str] = Field(default_factory=list)


class NewsEvent(DomainContractModel):
    event_id: str
    headline: str
    source: str
    published_at: datetime | None = None
    sentiment: Literal["POSITIVE", "NEGATIVE", "NEUTRAL", "UNKNOWN"] = "UNKNOWN"


class Scenario(DomainContractModel):
    scenario_id: str
    description: str
    probability: Literal["LOW", "MEDIUM", "HIGH"] | None = None
    impact: Literal["POSITIVE", "NEGATIVE", "NEUTRAL"] | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class ResearchRisk(DomainRisk):
    """研究层面的风险；复用通用 DomainRisk，避免语义重复。"""

    invalidation_conditions: list[str] = Field(default_factory=list)


class StockResearchResult(DomainContractModel):
    """股票客观研究结果。

    只回答"资产本身怎么样"，不回答"是否适合当前用户"；覆盖不足时
    ``coverage`` 为 PARTIAL/LIMITED，不允许包装成完整研究。
    """

    instrument: FinancialInstrument
    market_snapshot: MarketSnapshot | None = None
    fundamentals: Fundamentals | None = None
    valuation: Valuation | None = None
    technicals: Technicals | None = None
    money_flow: MoneyFlow | None = None
    industry_context: IndustryContext | None = None
    events: list[NewsEvent] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)
    risks: list[ResearchRisk] = Field(default_factory=list)
    evidence: list[EvidenceFact] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    coverage: Literal["COMPLETE", "PARTIAL", "LIMITED"] = "LIMITED"
    confidence: ConfidenceAssessment
    limitations: list[str] = Field(default_factory=list)


# ── 用户适配性结果（§10.3；必须区分资产质量与用户适配性） ──────────────────


class MarketRiskProxy(DomainContractModel):
    """Suitability v0 使用的历史市场风险代理，不是完整产品风险评级。"""

    band: Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"] = "UNKNOWN"
    max_drawdown_pct: float | None = Field(default=None, ge=0, le=100)
    annualized_volatility_pct: float | None = Field(default=None, ge=0)
    highest_research_risk_severity: Literal[
        "LOW", "MEDIUM", "HIGH", "CRITICAL"
    ] | None = None
    lookback_start: datetime | None = None
    lookback_end: datetime | None = None
    observation_count: int | None = Field(default=None, ge=0)
    annualization_trading_days: int = Field(default=244, gt=0)
    price_adjustment: Literal["FORWARD", "BACKWARD", "NONE", "UNKNOWN"] = "UNKNOWN"
    evidence_refs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_proxy_traceability(self) -> "MarketRiskProxy":
        has_objective_input = any(
            value is not None
            for value in (
                self.max_drawdown_pct,
                self.annualized_volatility_pct,
                self.highest_research_risk_severity,
            )
        )
        if self.band != "UNKNOWN" and not has_objective_input:
            raise ValueError("Known market risk proxy bands require objective inputs")
        if self.lookback_start and self.lookback_end:
            if self.lookback_start > self.lookback_end:
                raise ValueError("lookback_start must not be after lookback_end")
        return self


class SuitabilityRuleEvaluation(DomainContractModel):
    """一条固定规则的可审计输出；未知和不匹配均不得被聚合器丢弃。"""

    rule_id: Literal[
        "SUIT-RESEARCH-COVERAGE-001",
        "SUIT-DATA-AUTHENTICITY-001",
        "SUIT-RISK-LEVEL-001",
        "SUIT-MAX-LOSS-001",
        "SUIT-CONCENTRATION-001",
        "SUIT-LIQUIDITY-001",
        "SUIT-GOAL-HORIZON-001",
    ]
    outcome: Literal["PASS", "CONDITIONAL", "BLOCK", "UNKNOWN"]
    critical: bool
    reason_code: str = Field(min_length=1)
    public_reason: str = Field(min_length=1)
    actual_values: dict[str, JsonValue] = Field(default_factory=dict)
    threshold_values: dict[str, JsonValue] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence_refs(self) -> "SuitabilityRuleEvaluation":
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("Rule evidence_refs must contain stable unique references")
        if self.outcome != "UNKNOWN" and not self.evidence_refs:
            raise ValueError("Known rule outcomes require evidence_refs")
        return self


class ConcentrationThreshold(DomainContractModel):
    """严格大于阈值时分别进入 CONDITIONAL 和 BLOCK。"""

    conditional_above_pct: float = Field(ge=0, le=100)
    block_above_pct: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_order(self) -> "ConcentrationThreshold":
        if self.conditional_above_pct >= self.block_above_pct:
            raise ValueError("Conditional concentration threshold must be below block")
        return self


class MarketRiskProxyThresholds(DomainContractModel):
    """历史市场风险代理带的百分数点阈值；等号进入更严档。"""

    medium_max_drawdown_pct: float = Field(ge=0, le=100)
    high_max_drawdown_pct: float = Field(ge=0, le=100)
    medium_annualized_volatility_pct: float = Field(ge=0)
    high_annualized_volatility_pct: float = Field(ge=0)
    minimum_observation_count: int = Field(gt=1)
    annualization_trading_days: int = Field(default=244, gt=0)
    price_adjustment: Literal["FORWARD", "BACKWARD", "NONE"]

    @model_validator(mode="after")
    def validate_band_order(self) -> "MarketRiskProxyThresholds":
        if self.medium_max_drawdown_pct >= self.high_max_drawdown_pct:
            raise ValueError("Medium drawdown threshold must be below high")
        if (
            self.medium_annualized_volatility_pct
            >= self.high_annualized_volatility_pct
        ):
            raise ValueError("Medium volatility threshold must be below high")
        return self


class SuitabilityV0RuleSet(DomainContractModel):
    """七条固定规则的版本化政策契约。

    该模型只描述和校验规则配置，不代表配置已经获批。运行时只允许加载带审批引用的
    ``APPROVED`` 实例；当前 ADR-004 仍为 ``REVIEW_CHANGES_REQUIRED``。
    """

    version: str = Field(min_length=1)
    status: Literal["DRAFT", "REVIEW_CHANGES_REQUIRED", "APPROVED"]
    applicable_market: Literal["CN_A_SHARE_CASH"] = "CN_A_SHARE_CASH"
    supported_asset_types: set[Literal["STOCK"]] = Field(
        default_factory=lambda: {"STOCK"}
    )
    rule_ids: list[str] = Field(min_length=7, max_length=7)
    critical_rule_ids: set[str]
    market_risk_proxy_thresholds: MarketRiskProxyThresholds
    single_position_thresholds: dict[
        Literal["CONSERVATIVE", "BALANCED", "AGGRESSIVE"],
        ConcentrationThreshold,
    ]
    industry_thresholds: dict[
        Literal["CONSERVATIVE", "BALANCED", "AGGRESSIVE"],
        ConcentrationThreshold,
    ]
    liquidity_pass_buffer_ratio: float = Field(gt=1)
    liquidity_equal_to_needs_outcome: Literal["CONDITIONAL"] = "CONDITIONAL"
    max_loss_equal_outcome: Literal["CONDITIONAL"] = "CONDITIONAL"
    suitable_requires_confirmed_proposed_allocation: Literal[True] = True
    approval_ref: str | None = None
    approved_at: datetime | None = None

    @model_validator(mode="after")
    def validate_approval_and_completeness(self) -> "SuitabilityV0RuleSet":
        expected_profiles = {"CONSERVATIVE", "BALANCED", "AGGRESSIVE"}
        for field_name in ("single_position_thresholds", "industry_thresholds"):
            if set(getattr(self, field_name)) != expected_profiles:
                raise ValueError(f"{field_name} must define all risk profiles")
        if len(self.rule_ids) != len(set(self.rule_ids)):
            raise ValueError("Rule set rule_ids must be unique")
        if not self.critical_rule_ids.issubset(set(self.rule_ids)):
            raise ValueError("critical_rule_ids must be declared in rule_ids")
        if self.status == "APPROVED":
            if self.version.endswith("-draft"):
                raise ValueError("Approved rule set versions cannot end with -draft")
            if not self.approval_ref or self.approved_at is None:
                raise ValueError("Approved rule sets require approval_ref and approved_at")
        elif self.approval_ref is not None or self.approved_at is not None:
            raise ValueError("Unapproved rule sets cannot carry approval metadata")
        return self


class PortfolioImpact(DomainContractModel):
    current_exposure: dict[str, float] = Field(default_factory=dict)
    projected_exposure: dict[str, float] = Field(default_factory=dict)
    rule_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_exposure_percentages(self) -> "PortfolioImpact":
        for field_name in ("current_exposure", "projected_exposure"):
            values = getattr(self, field_name)
            invalid = [name for name, value in values.items() if not 0 <= value <= 100]
            if invalid:
                raise ValueError(
                    f"{field_name} values must use percentage points in 0..100"
                )
        return self


class GoalImpact(DomainContractModel):
    affected_goal_ids: list[str] = Field(default_factory=list)
    impact_level: Literal["NONE", "LOW", "MEDIUM", "HIGH"] = "NONE"
    reasons: list[str] = Field(default_factory=list)


class LiquidityImpact(DomainContractModel):
    status: Literal["OK", "CONSTRAINED", "UNKNOWN"] = "UNKNOWN"
    reasons: list[str] = Field(default_factory=list)


class RiskBudgetImpact(DomainContractModel):
    status: Literal["WITHIN_BUDGET", "NEAR_LIMIT", "EXCEEDS_LIMIT", "UNKNOWN"] = "UNKNOWN"
    reasons: list[str] = Field(default_factory=list)


class ConcentrationConflict(DomainContractModel):
    conflict_id: str
    exposure_type: str
    current_value: float | None = None
    projected_value: float | None = None
    threshold: float | None = None
    rule_id: str


class SuitabilityCondition(DomainContractModel):
    condition_id: str
    description: str
    verification_source: str


class SuitabilityAssessment(DomainContractModel):
    """个性化风险匹配筛查结果，不是买卖建议或完整法定适当性结论。"""

    assessment_kind: Literal["PERSONALIZED_RISK_MATCHING_SCREEN"] = (
        "PERSONALIZED_RISK_MATCHING_SCREEN"
    )
    rule_set_version: str = Field(min_length=1)
    rule_ids: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    result: Literal[
        "SUITABLE",
        "CONDITIONALLY_SUITABLE",
        "CURRENTLY_NOT_SUITABLE",
        "INSUFFICIENT_INFORMATION",
    ]
    market_risk_proxy: MarketRiskProxy | None = None
    rule_evaluations: list[SuitabilityRuleEvaluation] = Field(default_factory=list)
    proposed_allocation_confirmed: bool = False
    portfolio_impact: PortfolioImpact = Field(default_factory=PortfolioImpact)
    goal_impact: GoalImpact = Field(default_factory=GoalImpact)
    liquidity_impact: LiquidityImpact = Field(default_factory=LiquidityImpact)
    risk_budget_impact: RiskBudgetImpact = Field(default_factory=RiskBudgetImpact)
    concentration_conflicts: list[ConcentrationConflict] = Field(default_factory=list)
    required_conditions: list[SuitabilityCondition] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_rule_references(self) -> "SuitabilityAssessment":
        for field_name in ("rule_ids", "evidence_refs"):
            values = getattr(self, field_name)
            if len(values) != len(dict.fromkeys(values)):
                raise ValueError(f"{field_name} must contain stable unique references")
        evaluated_rule_ids = [item.rule_id for item in self.rule_evaluations]
        if len(evaluated_rule_ids) != len(set(evaluated_rule_ids)):
            raise ValueError("rule_evaluations must be unique by rule_id")
        if any(rule_id not in self.rule_ids for rule_id in evaluated_rule_ids):
            raise ValueError("Every evaluated rule must be declared in rule_ids")
        if self.result == "SUITABLE" and not self.proposed_allocation_confirmed:
            raise ValueError(
                "SUITABLE requires a controlled proposed allocation confirmation"
            )
        return self


# ── 金融领域输出边界（扩展通用 DomainOutcome） ─────────────────────────────


class FinancialDomainOutcome(DomainOutcome):
    """一次金融领域调用的输出边界。

    使用显式强类型字段携带领域结果（§7.3），禁止退回 ``list[dict]``；
    不包含最终聊天文案，表达由认知层负责。
    """

    domain: Literal["finance"] = "finance"
    financial_intent: FinancialIntent = FinancialIntent.STOCK_RESEARCH
    analysis_result: AnalysisResult | None = None
    stock_research_result: StockResearchResult | None = None
    suitability: SuitabilityAssessment | None = None
    portfolio_impact: PortfolioImpact | None = None
    goal_impact: GoalImpact | None = None
    liquidity_impact: LiquidityImpact | None = None
