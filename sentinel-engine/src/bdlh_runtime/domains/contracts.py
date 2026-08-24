"""通用领域请求/结果契约。

边界模型描述认知层与 Domain Runtime 的稳定接口，不承载实现逻辑：

- ``authenticated_user_id`` 只由服务端认证上下文提供，模型层不生成；
- 契约必须可序列化、可写入 Checkpointer（Pydantic 模型 + 显式字段）；
- ``DomainOutcome`` 不包含最终聊天文案——表达由认知层 CommunicationPlan 负责；
- ``status`` 不能被 LLM 表达改变，只接受枚举合法值；
- ``authorized_operations`` 表示领域授权操作，不命名为 ``allowed_actions``，
  避免与认知层行动（CognitiveAction）混淆；
- 跨层边界不退回 ``list[dict]`` 或无约束 ``dict``：Graph 内部如需字典状态，
  只能由本层模型 ``model_dump()`` 得到；
- 不保存模型隐藏思维链。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class DomainContractModel(BaseModel):
    """所有跨层领域契约的严格基类。"""

    model_config = ConfigDict(extra="forbid")


class DomainOperation(StrEnum):
    """领域授权操作集合；代表"允许领域做什么"，不是认知层行动。"""

    READ_MARKET_DATA = "READ_MARKET_DATA"
    READ_PUBLIC_RESEARCH = "READ_PUBLIC_RESEARCH"
    READ_PORTFOLIO = "READ_PORTFOLIO"
    READ_PROFILE = "READ_PROFILE"
    READ_FINANCIAL_GOALS = "READ_FINANCIAL_GOALS"
    RUN_ANALYSIS = "RUN_ANALYSIS"
    PROPOSE_TASK = "PROPOSE_TASK"


class GoalRef(DomainContractModel):
    """对本轮相关的用户目标的引用。"""

    goal_id: str
    description: str
    source: Literal[
        "USER_EXPLICIT",
        "PROFILE_CONFIRMED",
        "MEMORY_CONFIRMED",
        "TASK",
        "INFERRED",
    ]
    horizon: Literal["SHORT_TERM", "MEDIUM_TERM", "LONG_TERM"] | None = None
    target_date: datetime | None = None
    target_amount: float | None = Field(default=None, ge=0)


class DomainConstraint(DomainContractModel):
    """影响领域执行的用户约束（风险、期限、投资边界等）。"""

    constraint_id: str
    constraint_type: str
    description: str
    source: str
    materiality: Literal["LOW", "MEDIUM", "HIGH"]


class ContextRef(DomainContractModel):
    """对某个已持久化上下文（快照、历史、记忆等）的稳定引用。"""

    ref_type: str
    ref_id: str
    version: str | None = None


class DomainBudget(DomainContractModel):
    """一次领域调用的执行预算；超出预算必须返回 LIMITED/FAILED。"""

    tool_call_limit: int = Field(ge=0)
    runtime_seconds: int = Field(ge=1)
    model_call_limit: int = Field(default=0, ge=0)


class DomainFact(DomainContractModel):
    """带来源的事实条目（通用层）；金融层用 EvidenceFact 扩展。"""

    fact_id: str
    statement: str
    value: JsonValue = None
    source_refs: list[str] = Field(default_factory=list)
    directness: Literal["DIRECT", "DERIVED", "INFERRED"]


class DomainFinding(DomainContractModel):
    """基于事实与计算的结论；金融层用 Finding 扩展。"""

    finding_id: str
    statement: str
    evidence_ids: list[str] = Field(default_factory=list)
    calculation_ids: list[str] = Field(default_factory=list)
    confidence: Literal["HIGH", "MEDIUM", "LOW"]


class DomainRisk(DomainContractModel):
    """领域执行中识别出的风险。"""

    risk_id: str
    description: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    evidence_ids: list[str] = Field(default_factory=list)


class DomainConflict(DomainContractModel):
    """两条证据/结论之间的显式冲突，不得静默隐藏。"""

    conflict_id: str
    description: str
    left_refs: list[str]
    right_refs: list[str]
    materiality: Literal["LOW", "MEDIUM", "HIGH"]


class ConfidenceAssessment(DomainContractModel):
    """结果可信度：由覆盖率、时效、来源质量与冲突确定性计算。"""

    level: Literal["HIGH", "MEDIUM", "LOW"]
    reasons: list[str] = Field(default_factory=list)
    coverage_status: Literal["COMPLETE", "PARTIAL", "LIMITED"]


class DomainError(DomainContractModel):
    """稳定、可公开的领域失败信息。"""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    field: str | None = None
    retryable: bool = False


class RequiredUserDecision(DomainContractModel):
    """领域结果需要用户做出的关键选择。"""

    decision_id: str
    question: str
    reason: str
    allowed_choices: list[str] = Field(default_factory=list)


class SuggestedFollowup(DomainContractModel):
    """领域建议的后续行动（不含个性化承诺）。"""

    followup_type: str
    description: str
    trigger: JsonValue = None


class DomainRequest(DomainContractModel):
    """一次领域调用的输入边界。

    - ``authenticated_user_id`` 必须由服务端认证上下文提供，不得为空；
    - ``authorized_operations`` 是领域授权操作集合（只读/分析等）。
    """

    request_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    authenticated_user_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    goals: list[GoalRef] = Field(default_factory=list)
    constraints: list[DomainConstraint] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    context_refs: list[ContextRef] = Field(default_factory=list)
    authorized_operations: set[DomainOperation] = Field(min_length=1)
    budget: DomainBudget

    @model_validator(mode="after")
    def validate_identity(self) -> DomainRequest:
        if not self.authenticated_user_id.strip():
            raise ValueError("authenticated_user_id must come from the server auth context")
        return self


class DomainOutcome(DomainContractModel):
    """一次领域调用的输出边界。

    只包含结构化领域结果，不包含最终聊天文案；``status`` 只能取枚举合法值。
    """

    request_id: str
    domain: str
    status: Literal[
        "COMPLETE",
        "PARTIAL",
        "LIMITED",
        "FAILED",
        "WAITING_USER",
    ]
    established_facts: list[DomainFact] = Field(default_factory=list)
    findings: list[DomainFinding] = Field(default_factory=list)
    risks: list[DomainRisk] = Field(default_factory=list)
    conflicts: list[DomainConflict] = Field(default_factory=list)
    confidence: ConfidenceAssessment
    errors: list[DomainError] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    required_user_decisions: list[RequiredUserDecision] = Field(default_factory=list)
    suggested_followups: list[SuggestedFollowup] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_failure_errors(self) -> DomainOutcome:
        if self.status == "FAILED" and not self.errors:
            raise ValueError("FAILED DomainOutcome requires at least one DomainError")
        return self
