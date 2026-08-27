"""引擎运行时契约（设计文档 §4.3、§4.5）。

本模块承载 Agent 引擎的通用出入口契约：``InputEvent``（入口）、
``CognitiveExecution``（运行结果）、``PublicResponse``（对外回复）、
``CognitiveState``（可审计状态）、``CognitiveAction``（结构化决策）与
通用 ``DomainRequest`` 边界。SSE / checkpoint / 唤醒均经此契约。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: 未启用行动的稳定审计码（§7.2）：不能静默降级为 RESPOND。
ACTION_NOT_ENABLED = "ACTION_NOT_ENABLED"
RESPOND_UNAVAILABLE_REASON = "当前对话能力暂不可用，请稍后重试。"


class DomainOperation(StrEnum):
    """领域授权操作集合；代表「允许读取/分析什么」，不是认知层行动。"""

    READ_MARKET_DATA = "READ_MARKET_DATA"
    READ_PUBLIC_RESEARCH = "READ_PUBLIC_RESEARCH"
    READ_PORTFOLIO = "READ_PORTFOLIO"
    READ_PROFILE = "READ_PROFILE"
    READ_FINANCIAL_GOALS = "READ_FINANCIAL_GOALS"
    RUN_ANALYSIS = "RUN_ANALYSIS"
    PROPOSE_TASK = "PROPOSE_TASK"


class DomainBudget(BaseModel):
    """一次外部调用的执行预算。"""

    model_config = ConfigDict(extra="forbid")
    tool_call_limit: int = Field(ge=0)
    runtime_seconds: int = Field(ge=1)
    model_call_limit: int = Field(default=0, ge=0)


class DomainRequest(BaseModel):
    """INVOKE_DOMAIN 载荷（四时点 Guardrail 仍读取这些字段）。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    authenticated_user_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    success_criteria: list[str] = Field(default_factory=list)
    authorized_operations: set[DomainOperation] = Field(min_length=1)
    budget: DomainBudget

    @model_validator(mode="after")
    def validate_identity(self) -> DomainRequest:
        if not self.authenticated_user_id.strip():
            raise ValueError("authenticated_user_id must come from the server auth context")
        return self


class SuccessCriterion(BaseModel):
    """一条可判定的成功标准（checkpoint 状态内嵌）。"""

    model_config = ConfigDict(extra="forbid")
    criterion_id: str = Field(min_length=1)
    topic: str | None = None
    description: str = Field(min_length=1)
    candidate_capabilities: list[str] = Field(default_factory=list)
    observation_refs: list[str] = Field(default_factory=list)


class GoalSpec(BaseModel):
    """checkpoint 中的最小可验证任务单元。"""

    model_config = ConfigDict(extra="forbid")
    goal_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    requested_topics: list[str] = Field(default_factory=list)
    needs_account: bool = False
    needs_profile: bool = False
    success_criteria: list[SuccessCriterion] = Field(min_length=1)
    status: Literal["PENDING", "COVERED", "BLOCKED"] = "PENDING"
    observation_refs: list[str] = Field(default_factory=list)


class CognitiveActionType(StrEnum):
    """认知层九种候选行动；契约必须支持全部，Policy 决定启用集合。"""

    RESPOND = "RESPOND"
    ASK_USER = "ASK_USER"
    INVOKE_DOMAIN = "INVOKE_DOMAIN"
    RETRIEVE_MEMORY = "RETRIEVE_MEMORY"
    CREATE_TASK = "CREATE_TASK"
    UPDATE_TASK = "UPDATE_TASK"
    WAIT = "WAIT"
    NOTIFY = "NOTIFY"
    DO_NOTHING = "DO_NOTHING"


class InputEventType(StrEnum):
    """进入 Cognitive Kernel 的事件来源；M6 Scheduler 只能投递唤醒事件。"""

    USER_MESSAGE = "USER_MESSAGE"
    SCHEDULED_WAKEUP = "SCHEDULED_WAKEUP"


#: M4 Action Policy 启用的行动集合（§11.4.2）。
ENABLED_ACTION_TYPES: frozenset[CognitiveActionType] = frozenset(
    {
        CognitiveActionType.RESPOND,
        CognitiveActionType.ASK_USER,
        CognitiveActionType.INVOKE_DOMAIN,
    }
)


class CognitiveAction(BaseModel):
    """认知层对"下一步做什么"的结构化决策。

    ``domain_request`` 只允许伴随 ``INVOKE_DOMAIN``；其余行动不得偷带领域
    请求。``reason_code`` 是稳定审计码，供 Policy 与可观测性使用。
    """

    model_config = ConfigDict(extra="forbid")

    action_type: CognitiveActionType
    reason_code: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    related_goal_ids: list[str] = Field(default_factory=list)
    domain_request: DomainRequest | None = None
    task_spec_ref: str | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> CognitiveAction:
        if self.action_type == CognitiveActionType.INVOKE_DOMAIN and self.domain_request is None:
            raise ValueError("INVOKE_DOMAIN requires a domain_request payload")
        if self.action_type != CognitiveActionType.INVOKE_DOMAIN and self.domain_request is not None:
            raise ValueError("only INVOKE_DOMAIN may carry a domain_request payload")
        return self


class InputEvent(BaseModel):
    """M4 顶层编排的严格入口；身份与会话均由网关注入。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    event_type: InputEventType = InputEventType.USER_MESSAGE
    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=20_000)
    run_id: str | None = None
    task_id: str | None = None
    # 唤醒事件所属域，供 handler 注册表路由；用户消息不使用。
    task_domain: str | None = None
    # 会话级 Skill 开关快照：None 表示未声明，空/非空集合表示本轮显式启用列表。
    enabled_skills: frozenset[str] | None = None

    @model_validator(mode="after")
    def validate_event_source(self) -> InputEvent:
        if self.event_type == InputEventType.SCHEDULED_WAKEUP and not self.task_id:
            raise ValueError("SCHEDULED_WAKEUP requires task_id")
        if self.event_type == InputEventType.SCHEDULED_WAKEUP and not self.task_domain:
            raise ValueError("SCHEDULED_WAKEUP requires task_domain")
        if self.event_type != InputEventType.SCHEDULED_WAKEUP and self.task_id is not None:
            raise ValueError("task_id is reserved for SCHEDULED_WAKEUP")
        if self.event_type != InputEventType.SCHEDULED_WAKEUP and self.task_domain is not None:
            raise ValueError("task_domain is reserved for SCHEDULED_WAKEUP")
        return self


class CognitiveState(BaseModel):
    """M4 编排的最小可审计状态；不保存原始供应商数据或隐藏推理。"""

    model_config = ConfigDict(extra="forbid")

    event: InputEvent
    situation_summary: str | None = None
    uncertainty_codes: list[str] = Field(default_factory=list)
    goals: list[GoalSpec] = Field(default_factory=list)
    needs_external: bool = False
    action: CognitiveActionSummary | None = None
    action_history: list[CognitiveActionSummary] = Field(default_factory=list)
    domain_request_refs: list[str] = Field(default_factory=list)
    domain_outcome_refs: list[str] = Field(default_factory=list)
    domain_calls_used: int = Field(default=0, ge=0)
    requested_tool_calls: int = Field(default=0, ge=0)
    requested_runtime_seconds: int = Field(default=0, ge=0)
    communication_plan: CommunicationPlan | None = None
    public_events: list[str] = Field(default_factory=list)
    error_codes: list[str] = Field(default_factory=list)


class CognitiveActionSummary(BaseModel):
    """可持久化的行动摘要；不携带完整领域请求或供应商数据。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_type: CognitiveActionType
    reason_code: str = Field(min_length=1)
    related_goal_ids: list[str] = Field(default_factory=list)
    domain_request_ref: str | None = None

    @classmethod
    def from_action(cls, action: CognitiveAction) -> CognitiveActionSummary:
        return cls(
            action_type=action.action_type,
            reason_code=action.reason_code,
            related_goal_ids=list(action.related_goal_ids),
            domain_request_ref=(action.domain_request.request_id if action.domain_request else None),
        )


class CommunicationPlan(BaseModel):
    """表达计划，只引用领域结果，不得修改领域事实。"""

    model_config = ConfigDict(extra="forbid")

    response_kind: Literal[
        "ANSWER",
        "ASK_USER",
        "DOMAIN_RESULT",
        "LIMITED",
        "BLOCKED",
        "CAPABILITY_NOT_ENABLED",
    ]
    response_structure: Literal[
        "KNOWLEDGE",
        "CLARIFICATION",
        "RESEARCH",
        "SUITABILITY",
        "PORTFOLIO_IMPACT",
        "GOAL_PLANNING",
        "CAPABILITY_NOTICE",
        "SAFETY_BLOCK",
    ] = "KNOWLEDGE"
    summary: str = Field(min_length=1)
    sections: list[CommunicationSection] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    data_times: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    risk_disclosures: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class PublicResponse(BaseModel):
    """对 SSE/JSON 稳定暴露的 M4 回复契约。"""

    model_config = ConfigDict(extra="forbid")

    response_kind: Literal[
        "ANSWER",
        "ASK_USER",
        "DOMAIN_RESULT",
        "LIMITED",
        "BLOCKED",
        "CAPABILITY_NOT_ENABLED",
    ]
    response_structure: Literal[
        "KNOWLEDGE",
        "CLARIFICATION",
        "RESEARCH",
        "SUITABILITY",
        "PORTFOLIO_IMPACT",
        "GOAL_PLANNING",
        "CAPABILITY_NOTICE",
        "SAFETY_BLOCK",
    ] = "KNOWLEDGE"
    message: str = Field(min_length=1)
    sections: list[CommunicationSection] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    data_times: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    risk_disclosures: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    audit_codes: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)


class CommunicationSection(BaseModel):
    """公开回复中的可渲染分区，不承载隐藏推理。"""

    model_config = ConfigDict(extra="forbid")

    section_type: Literal["SUMMARY", "FACTS", "FINDINGS", "RISKS", "LIMITATIONS", "NEXT_STEPS"]
    title: str = Field(min_length=1)
    items: list[str] = Field(min_length=1)


class CognitiveExecution(BaseModel):
    """一次引擎运行的对外结果（SSE / checkpoint / 唤醒共用）。"""

    model_config = ConfigDict(extra="forbid")

    state: CognitiveState
    response: PublicResponse
    checkpoint: Any = None
    observations: list[dict[str, Any]] = Field(default_factory=list)
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    entered_loop: bool = False
    fastpath_name: str | None = None
    loaded_tools: list[str] = Field(default_factory=list)


def is_action_enabled(action_type: CognitiveActionType) -> bool:
    """M4 默认 Action Policy 是否启用该行动。"""
    return action_type in ENABLED_ACTION_TYPES
