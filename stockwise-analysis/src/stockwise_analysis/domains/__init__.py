"""领域编排与跨层契约层（标记：``SW31-P1-DOMAIN-CONTRACTS``）。

与既有 ``stockwise_analysis.domain``（纯确定性金融计算层）明确分离：
- ``domain/``   = 确定性计算，禁止依赖 LangGraph / LangChain / MCP / Mem0；
- ``domains/``  = 领域编排与跨层契约，可依赖 Adapter / Registry / Graph。

本包承载通用契约与领域运行时；具体金融计算仍只存在于 ``domain/``。
"""

from .contracts import (
    ConfidenceAssessment,
    ContextRef,
    DomainBudget,
    DomainConstraint,
    DomainConflict,
    DomainContractModel,
    DomainError,
    DomainFact,
    DomainFinding,
    DomainOperation,
    DomainOutcome,
    DomainRequest,
    DomainRisk,
    GoalRef,
    RequiredUserDecision,
    SuggestedFollowup,
)
from .registry import DomainRegistry

__all__ = [
    "ConfidenceAssessment",
    "ContextRef",
    "DomainBudget",
    "DomainConstraint",
    "DomainConflict",
    "DomainContractModel",
    "DomainError",
    "DomainFact",
    "DomainFinding",
    "DomainOperation",
    "DomainOutcome",
    "DomainRequest",
    "DomainRisk",
    "DomainRegistry",
    "GoalRef",
    "RequiredUserDecision",
    "SuggestedFollowup",
]
