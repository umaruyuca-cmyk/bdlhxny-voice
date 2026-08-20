"""M4 Guardrail 通用结果契约。

本模块定义四时点共享的强类型结果；默认策略由 ``policies.py`` 实现并接入
独立 Cognitive 编排。``replacement`` 使用泛型，使计划、动作、Observation
和回复可以分别被各自接口安全替换，避免绑定旧 ``AgentAction``。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GuardrailStage(StrEnum):
    """四个不可合并的策略检查时点。"""

    PLAN = "plan"
    ACTION = "action"
    DATA_QUALITY = "data_quality"
    RESPONSE = "response"


class GuardrailDecision(StrEnum):
    """Guardrail 对当前对象的处理决定。"""

    ALLOW = "allow"
    BLOCK = "block"
    MODIFY = "modify"
    ASK_USER = "ask_user"


class GuardrailContext(BaseModel):
    """由服务端构造的最小策略上下文，不接收隐藏思维链或原始凭证。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    authenticated_user_id: str = Field(min_length=1)
    read_only: bool = True
    authorized_capabilities: frozenset[str] = frozenset()
    enabled_domains: frozenset[str] = frozenset()
    authorized_operations: frozenset[str] = frozenset()
    enabled_actions: frozenset[str] = frozenset()
    max_tool_calls: int = Field(default=20, ge=0)
    max_runtime_seconds: int = Field(default=120, ge=1)


ReplacementT = TypeVar("ReplacementT")


class GuardrailResult(BaseModel, Generic[ReplacementT]):
    """一次 Guardrail 检查的统一结果。

    ``modify`` 必须携带同类型替换对象；其他决定不得偷带替换对象。
    除 ``allow`` 外均要求稳定 ``audit_code`` 和至少一条公开理由。
    """

    model_config = ConfigDict(extra="forbid")

    stage: GuardrailStage
    decision: GuardrailDecision
    reasons: list[str] = Field(default_factory=list)
    replacement: ReplacementT | None = None
    audit_code: str | None = None
    rule_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_decision_payload(self) -> GuardrailResult[ReplacementT]:
        if self.decision == GuardrailDecision.MODIFY and self.replacement is None:
            raise ValueError("modify decisions require a replacement")
        if self.decision != GuardrailDecision.MODIFY and self.replacement is not None:
            raise ValueError("only modify decisions may carry a replacement")
        if self.decision != GuardrailDecision.ALLOW:
            if not self.audit_code or not self.audit_code.strip():
                raise ValueError("non-allow decisions require a stable audit_code")
            if not self.reasons:
                raise ValueError("non-allow decisions require at least one reason")
        return self
