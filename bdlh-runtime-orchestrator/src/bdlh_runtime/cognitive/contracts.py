"""认知行动契约（31 号统一开发实施 Prompt §7.2、§11.5）。

实施标记：``SW31-M4-COGNITIVE-ACTION``。本模块定义 M4 认知行动、状态与
公开表达边界；运行时 Action Policy 与独立编排由同包实现。

``CognitiveAction`` 是认知层唯一行动模型（架构概念 ``NextAction`` 不创建
第二个同义模型）；旧 ReAct 层的 ``AgentAction`` 是数据获取层的工具动作
模型，两者分属不同层，本模块不删除、不改名旧模型。

第一阶段 Action Policy 只允许 ``RESPOND / ASK_USER / INVOKE_DOMAIN``；
其余枚举值必须返回稳定审计码 ``ACTION_NOT_ENABLED``，不能静默降级为
``RESPOND``。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bdlh_runtime.domains.contracts import DomainRequest

from .goal_schema import GoalSpec

#: 未启用行动的稳定审计码（§7.2）：不能静默降级为 RESPOND。
ACTION_NOT_ENABLED = "ACTION_NOT_ENABLED"


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
    # 会话级 Skill 开关快照：None 表示不限制（内部入口与旧客户端），
    # 空/非空集合表示本轮显式声明的启用列表。finance Skill 仅「允许」金融域派发，
    # 未命中金融信号时仍走普通对话；不参与权限与资格计算（权限真源仍是 Registry）。
    enabled_skills: frozenset[str] | None = None

    @model_validator(mode="after")
    def validate_event_source(self) -> InputEvent:
        if self.event_type == InputEventType.SCHEDULED_WAKEUP and not self.task_id:
            raise ValueError("SCHEDULED_WAKEUP requires task_id")
        if self.event_type != InputEventType.SCHEDULED_WAKEUP and self.task_id is not None:
            raise ValueError("task_id is reserved for SCHEDULED_WAKEUP")
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


def is_action_enabled(action_type: CognitiveActionType) -> bool:
    """M4 默认 Action Policy 是否启用该行动。"""
    return action_type in ENABLED_ACTION_TYPES
