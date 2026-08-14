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

from pydantic import Field, model_validator

from stockwise_analysis.contracts.analysis import AnalysisResult
from stockwise_analysis.domains.contracts import (
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


class FinancialDomainRequest(DomainRequest):
    """一次金融领域调用的输入边界。"""

    domain: Literal["finance"] = "finance"
    financial_intent: FinancialIntent = FinancialIntent.STOCK_RESEARCH
    analysis_type: Literal[
        "market_snapshot",
        "technical",
        "fundamental",
        "valuation",
        "comprehensive",
    ] = "market_snapshot"
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
        if self.financial_intent == FinancialIntent.STOCK_RESEARCH and len(self.instruments) != 1:
            raise ValueError("STOCK_RESEARCH requires exactly one instrument")
        if self.financial_intent == FinancialIntent.SUITABILITY and not self.instruments:
            raise ValueError("SUITABILITY requires at least one instrument")
        return self


# ── 最小金融快照（阶段 4 SuitabilityEngine 输入，数据缺失如实标记） ────────


class PortfolioPosition(DomainContractModel):
    """用户当前持仓条目。"""

    symbol: str
    name: str | None = None
    quantity: float | None = None
    market_value: float | None = None
    weight_pct: float | None = None
    industry: str | None = None
    source: str


class AccountSnapshot(DomainContractModel):
    """账户级快照。"""

    total_assets: float | None = None
    cash: float | None = None
    currency: str = "CNY"
    source: str


class RiskProfile(DomainContractModel):
    """用户风险画像；缺失字段为 None 时视为信息不足。"""

    risk_level: Literal["CONSERVATIVE", "BALANCED", "AGGRESSIVE"] | None = None
    max_loss_tolerance_pct: float | None = None
    source: str


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
    liquid_assets: float | None = None
    near_term_cash_needs: float | None = None
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
    indicators: dict[str, float] = Field(default_factory=dict)
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


class PortfolioImpact(DomainContractModel):
    current_exposure: dict[str, float] = Field(default_factory=dict)
    projected_exposure: dict[str, float] = Field(default_factory=dict)
    rule_ids: list[str] = Field(default_factory=list)


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
    """用户适配性结果（结合 StockResearchResult + FinancialSnapshot）。"""

    result: Literal[
        "SUITABLE",
        "CONDITIONALLY_SUITABLE",
        "CURRENTLY_NOT_SUITABLE",
        "INSUFFICIENT_INFORMATION",
    ]
    portfolio_impact: PortfolioImpact = Field(default_factory=PortfolioImpact)
    goal_impact: GoalImpact = Field(default_factory=GoalImpact)
    liquidity_impact: LiquidityImpact = Field(default_factory=LiquidityImpact)
    risk_budget_impact: RiskBudgetImpact = Field(default_factory=RiskBudgetImpact)
    concentration_conflicts: list[ConcentrationConflict] = Field(default_factory=list)
    required_conditions: list[SuitabilityCondition] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


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
