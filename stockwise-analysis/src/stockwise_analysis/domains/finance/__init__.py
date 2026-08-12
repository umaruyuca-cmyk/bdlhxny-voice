"""金融领域契约层（标记：``SW31-P1-DOMAIN-CONTRACTS``）。

第一阶段只承载金融领域的边界契约：
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

__all__ = [
    "AccountSnapshot",
    "ConcentrationConflict",
    "EvidenceConflict",
    "EvidenceFact",
    "FinancialDomainOutcome",
    "FinancialDomainRequest",
    "FinancialDataMode",
    "FinancialGoal",
    "FinancialInstrument",
    "FinancialIntent",
    "FinancialSnapshot",
    "Finding",
    "Fundamentals",
    "GoalImpact",
    "IndustryContext",
    "LiquidityImpact",
    "LiquiditySnapshot",
    "MarketSnapshot",
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
]
