"""金融领域契约、M1 Runtime、M2 Research 与 M3 Snapshot 基础模块。

公开边界包括：
- ``FinancialDomainRequest / FinancialDomainOutcome``（扩展通用 DomainRequest/Outcome）；
- ``FinancialSnapshot``（最小金融快照，M3 Suitability 的输入）；
- ``StockResearchResult``（客观研究结构化结果，M2 下沉目标）；
- ``SuitabilityAssessment``（用户适配性结果，M3 输出）；
- ``EvidenceFact / Finding / EvidenceConflict``（证据与结论，扩展通用契约）。
"""

from .contracts import (
    AccountSnapshot,
    ConcentrationConflict,
    EvidenceConflict,
    EvidenceFact,
    FinancialDomainOutcome,
    FinancialDomainRequest,
    FinancialDataMode,
    FinancialGoal,
    FinancialInstrument,
    FinancialIntent,
    FinancialSnapshot,
    Finding,
    Fundamentals,
    GoalImpact,
    IndustryContext,
    InstrumentCandidate,
    InstrumentMention,
    InstrumentResolutionOutcome,
    InstrumentResolutionRequest,
    LiquidityImpact,
    LiquiditySnapshot,
    MarketSnapshot,
    MoneyFlow,
    NewsEvent,
    PortfolioImpact,
    PortfolioPosition,
    ResearchRisk,
    RiskBudgetImpact,
    RiskProfile,
    Scenario,
    StockResearchResult,
    SuitabilityAssessment,
    SuitabilityCondition,
    Technicals,
    Valuation,
)
from .authorization import (
    ANALYSIS_CAPABILITY,
    AuthorizationDecision,
    FinanceCapabilityAuthorizationPolicy,
    M1_OPERATION_CAPABILITIES,
    M3_OPERATION_CAPABILITIES,
)
from .planner import FinancePlan, FinancePlanner
from .instrument_resolver import (
    FinanceInstrumentResolver,
    RESOLVE_INSTRUMENT_CAPABILITY,
)
from .research_builder import StockResearchResultBuilder
from .snapshot_builder import (
    FinancialSnapshotBuilder,
    FinancialSnapshotError,
    SnapshotIdentityError,
    UserFinancialObservationNormalizer,
)
from .valuation_builder import (
    PortfolioValuationBuilder,
    PortfolioValuationError,
)
from .suitability_preflight import (
    PENDING_RULE_IDS,
    PENDING_RULE_SET_VERSION,
    SuitabilityPreflight,
    SuitabilityPreflightError,
)
from .runtime import (
    ApplicationFinanceCapabilityExecutor,
    FinanceCapabilityExecutor,
    FinanceRunState,
    FinanceRuntime,
    create_finance_runtime,
)
from .manifests import (
    FINANCE_DESCRIPTOR,
    PORTFOLIO_HEALTH_MANIFEST,
    STOCK_RESEARCH_MANIFEST,
    SUITABILITY_MANIFEST,
)

__all__ = [
    "AccountSnapshot",
    "ANALYSIS_CAPABILITY",
    "AuthorizationDecision",
    "ConcentrationConflict",
    "EvidenceConflict",
    "EvidenceFact",
    "FinancialDomainOutcome",
    "FinancialDomainRequest",
    "FinancialDataMode",
    "FinancialGoal",
    "FinancialInstrument",
    "FinancialIntent",
    "FinanceCapabilityAuthorizationPolicy",
    "FinancePlan",
    "FinancePlanner",
    "FinanceCapabilityExecutor",
    "FinanceRunState",
    "FinanceRuntime",
    "FinanceInstrumentResolver",
    "FINANCE_DESCRIPTOR",
    "FinancialSnapshot",
    "FinancialSnapshotBuilder",
    "FinancialSnapshotError",
    "Finding",
    "Fundamentals",
    "GoalImpact",
    "IndustryContext",
    "InstrumentCandidate",
    "InstrumentMention",
    "InstrumentResolutionOutcome",
    "InstrumentResolutionRequest",
    "LiquidityImpact",
    "LiquiditySnapshot",
    "MarketSnapshot",
    "M1_OPERATION_CAPABILITIES",
    "M3_OPERATION_CAPABILITIES",
    "MoneyFlow",
    "NewsEvent",
    "PortfolioImpact",
    "PortfolioPosition",
    "PORTFOLIO_HEALTH_MANIFEST",
    "PortfolioValuationBuilder",
    "PortfolioValuationError",
    "PENDING_RULE_IDS",
    "PENDING_RULE_SET_VERSION",
    "ResearchRisk",
    "RESOLVE_INSTRUMENT_CAPABILITY",
    "RiskBudgetImpact",
    "RiskProfile",
    "Scenario",
    "StockResearchResult",
    "StockResearchResultBuilder",
    "STOCK_RESEARCH_MANIFEST",
    "SnapshotIdentityError",
    "SuitabilityAssessment",
    "SuitabilityCondition",
    "SuitabilityPreflight",
    "SuitabilityPreflightError",
    "SUITABILITY_MANIFEST",
    "Technicals",
    "Valuation",
    "UserFinancialObservationNormalizer",
    "ApplicationFinanceCapabilityExecutor",
    "create_finance_runtime",
]
