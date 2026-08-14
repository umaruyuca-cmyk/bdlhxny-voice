"""金融领域的契约、授权、规划与 M1 薄运行时。

公开边界包括：
- ``FinancialDomainRequest / FinancialDomainOutcome``（扩展通用 DomainRequest/Outcome）；
- ``FinancialSnapshot``（最小金融快照，阶段 4 Suitability 的输入）；
- ``StockResearchResult``（客观研究结构化结果，阶段 3 下沉目标）；
- ``SuitabilityAssessment``（用户适配性结果，阶段 4 输出）；
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
)
from .planner import FinancePlan, FinancePlanner
from .runtime import (
    ApplicationFinanceCapabilityExecutor,
    FinanceCapabilityExecutor,
    FinanceRunState,
    FinanceRuntime,
    create_finance_runtime,
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
    "FinancialSnapshot",
    "Finding",
    "Fundamentals",
    "GoalImpact",
    "IndustryContext",
    "LiquidityImpact",
    "LiquiditySnapshot",
    "MarketSnapshot",
    "M1_OPERATION_CAPABILITIES",
    "MoneyFlow",
    "NewsEvent",
    "PortfolioImpact",
    "PortfolioPosition",
    "ResearchRisk",
    "RiskBudgetImpact",
    "RiskProfile",
    "Scenario",
    "StockResearchResult",
    "SuitabilityAssessment",
    "SuitabilityCondition",
    "Technicals",
    "Valuation",
    "ApplicationFinanceCapabilityExecutor",
    "create_finance_runtime",
]
