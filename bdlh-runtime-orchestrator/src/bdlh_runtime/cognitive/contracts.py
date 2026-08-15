"""认知行动契约（31 号统一开发实施 Prompt §7.2、§11.5）。

实施标记：``SW31-P1-COGNITIVE-ACTION``。本模块仅定义认知行动边界；
Cognitive Graph 与运行时 Action Policy 仍由阶段 5 实现。

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

from bdlh_runtime.domains.contracts import DomainOutcome, DomainRequest

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


#: 第一阶段 Action Policy 启用的行动集合（§7.2）。
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
    def validate_payload(self) -> "CognitiveAction":
        if self.action_type == CognitiveActionType.INVOKE_DOMAIN and self.domain_request is None:
            raise ValueError("INVOKE_DOMAIN requires a domain_request payload")
        if self.action_type != CognitiveActionType.INVOKE_DOMAIN and self.domain_request is not None:
            raise ValueError("only INVOKE_DOMAIN may carry a domain_request payload")
        return self


class InputEvent(BaseModel):
    """M4 顶层编排的严格入口；身份与会话均由网关注入。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=20_000)
    run_id: str | None = None


class CognitiveState(BaseModel):
    """M4 编排的最小可审计状态；不保存原始供应商数据或隐藏推理。"""

    model_config = ConfigDict(extra="forbid")

    event: InputEvent
    situation_summary: str | None = None
    uncertainty_codes: list[str] = Field(default_factory=list)
    action: CognitiveAction | None = None
    domain_request: DomainRequest | None = None
    domain_outcome: DomainOutcome | None = None
    communication_plan: "CommunicationPlan | None" = None
    public_events: list[str] = Field(default_factory=list)
    error_codes: list[str] = Field(default_factory=list)


class CommunicationPlan(BaseModel):
    """表达计划，只引用领域结果，不得修改领域事实。"""

    model_config = ConfigDict(extra="forbid")

    response_kind: Literal["ANSWER", "ASK_USER", "DOMAIN_RESULT", "LIMITED", "BLOCKED"]
    summary: str = Field(min_length=1)
    required_fields: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class PublicResponse(BaseModel):
    """对 SSE/JSON 稳定暴露的 M4 回复契约。"""

    model_config = ConfigDict(extra="forbid")

    response_kind: Literal["ANSWER", "ASK_USER", "DOMAIN_RESULT", "LIMITED", "BLOCKED"]
    message: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    audit_codes: list[str] = Field(default_factory=list)


def is_action_enabled(action_type: CognitiveActionType) -> bool:
    """第一阶段 Policy 简表：行动是否在启用集合内（阶段 5 前的最小策略）。"""
    return action_type in ENABLED_ACTION_TYPES
