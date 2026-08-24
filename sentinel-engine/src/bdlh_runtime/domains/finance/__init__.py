"""金融领域契约、M1 Runtime、M2 Research 与 M3 Snapshot 基础模块。

公开边界包括：
- ``FinancialDomainRequest / FinancialDomainOutcome``（扩展通用 DomainRequest/Outcome）；
- ``FinancialSnapshot``（最小金融快照，M3 Suitability 的输入）；
- ``StockResearchResult``（客观研究结构化结果，M2 下沉目标）；
- ``SuitabilityAssessment``（用户适配性结果，M3 输出）；
- ``EvidenceFact / Finding / EvidenceConflict``（证据与结论，扩展通用契约）。
"""

from .authorization import (
    ANALYSIS_CAPABILITY,
    AuthorizationDecision,
    FinanceCapabilityAuthorizationPolicy,
)
from .contracts import (
    AccountSnapshot,
    ConcentrationConflict,
    ConcentrationThreshold,
    EvidenceConflict,
    EvidenceFact,
    FinancialDataMode,
    FinancialDataReference,
    FinancialDomainOutcome,
    FinancialDomainRequest,
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
    MarketRiskProxy,
    MarketRiskProxyThresholds,
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
    SuitabilityRuleEvaluation,
    SuitabilityV0RuleSet,
    Technicals,
    Valuation,
)
from .instrument_resolver import (
    RESOLVE_INSTRUMENT_CAPABILITY,
    FinanceInstrumentResolver,
)
from .manifests import build_finance_descriptor
from .planner import FinancePlan, FinancePlanner
from .research_builder import StockResearchResultBuilder
from .runtime import (
    ApplicationFinanceCapabilityExecutor,
    FinanceCapabilityExecutor,
    FinanceRunState,
    FinanceRuntime,
    create_finance_runtime,
)
from .snapshot_builder import (
    FinancialSnapshotBuilder,
    FinancialSnapshotError,
    SnapshotIdentityError,
    UserFinancialObservationNormalizer,
)
from .suitability_engine import SuitabilityEngine
from .suitability_preflight import (
    PENDING_RULE_IDS,
    PENDING_RULE_SET_VERSION,
    SuitabilityPreflight,
    SuitabilityPreflightError,
)
from .suitability_v0_ruleset import default_suitability_v0_rule_set
from .valuation_builder import (
    PortfolioValuationBuilder,
    PortfolioValuationError,
    PortfolioValuationInput,
)

__all__ = [
    "AccountSnapshot",
    "ANALYSIS_CAPABILITY",
    "AuthorizationDecision",
    "ConcentrationConflict",
    "ConcentrationThreshold",
    "EvidenceConflict",
    "EvidenceFact",
    "FinancialDomainOutcome",
    "FinancialDomainRequest",
    "FinancialDataMode",
    "FinancialDataReference",
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
    "build_finance_descriptor",
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
    "MarketRiskProxy",
    "MarketRiskProxyThresholds",
    "MoneyFlow",
    "NewsEvent",
    "PortfolioImpact",
    "PortfolioPosition",
    "PortfolioValuationBuilder",
    "PortfolioValuationError",
    "PortfolioValuationInput",
    "PENDING_RULE_IDS",
    "PENDING_RULE_SET_VERSION",
    "ResearchRisk",
    "RESOLVE_INSTRUMENT_CAPABILITY",
    "RiskBudgetImpact",
    "RiskProfile",
    "Scenario",
    "StockResearchResult",
    "StockResearchResultBuilder",
    "SnapshotIdentityError",
    "SuitabilityAssessment",
    "SuitabilityCondition",
    "SuitabilityEngine",
    "SuitabilityRuleEvaluation",
    "SuitabilityV0RuleSet",
    "SuitabilityPreflight",
    "SuitabilityPreflightError",
    "Technicals",
    "Valuation",
    "UserFinancialObservationNormalizer",
    "ApplicationFinanceCapabilityExecutor",
    "create_finance_runtime",
    "default_suitability_v0_rule_set",
]
