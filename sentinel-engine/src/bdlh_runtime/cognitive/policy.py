"""M4 领域无关 Action Policy。"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from .contracts import (
    ACTION_NOT_ENABLED,
    ENABLED_ACTION_TYPES,
    CognitiveAction,
    CognitiveActionType,
)


class ActionPolicyResult(BaseModel):
    """Action Policy 的稳定可审计决定。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal["ENABLED", "REJECTED"]
    action: CognitiveAction
    audit_code: str | None = None
    public_reason: str | None = None


class ActionPolicy(Protocol):
    @property
    def enabled_actions(self) -> frozenset[CognitiveActionType]: ...

    def evaluate(self, action: CognitiveAction) -> ActionPolicyResult: ...


class DefaultActionPolicy:
    """M4 仅开放 RESPOND、ASK_USER、INVOKE_DOMAIN。"""

    def __init__(
        self,
        enabled_actions: frozenset[CognitiveActionType] = ENABLED_ACTION_TYPES,
    ) -> None:
        self._enabled_actions = enabled_actions

    @property
    def enabled_actions(self) -> frozenset[CognitiveActionType]:
        return self._enabled_actions

    def evaluate(self, action: CognitiveAction) -> ActionPolicyResult:
        if action.action_type not in self._enabled_actions:
            return ActionPolicyResult(
                decision="REJECTED",
                action=action,
                audit_code=ACTION_NOT_ENABLED,
                public_reason=f"{action.action_type.value} 能力当前未启用。",
            )
        return ActionPolicyResult(decision="ENABLED", action=action)
