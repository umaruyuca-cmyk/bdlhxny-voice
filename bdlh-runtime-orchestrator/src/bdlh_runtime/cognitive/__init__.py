"""最小深层认知内核（标记：``SW31-P1-COGNITIVE-ACTION``）。

M4 提供独立、非默认流量的认知契约与受控编排。
"""

from .contracts import (
    ACTION_NOT_ENABLED,
    CognitiveAction,
    CognitiveActionSummary,
    CognitiveActionType,
    CognitiveState,
    CommunicationSection,
    CommunicationPlan,
    InputEvent,
    InputEventType,
    PublicResponse,
)
from .policy import ActionPolicyResult, DefaultActionPolicy

__all__ = [
    "ACTION_NOT_ENABLED",
    "ActionPolicyResult",
    "CognitiveAction",
    "CognitiveActionSummary",
    "CognitiveActionType",
    "CognitiveState",
    "CommunicationSection",
    "DefaultActionPolicy",
    "CommunicationPlan",
    "InputEvent",
    "InputEventType",
    "PublicResponse",
]
