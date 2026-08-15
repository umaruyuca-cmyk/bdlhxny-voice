"""最小深层认知内核（标记：``SW31-P1-COGNITIVE-ACTION``）。

第一阶段只承载认知层契约（``CognitiveAction``）；Cognitive Graph /
Action Policy 等运行时在阶段 5 实现。
"""

from .contracts import (
    ACTION_NOT_ENABLED,
    CognitiveAction,
    CognitiveActionType,
    CognitiveState,
    CommunicationPlan,
    InputEvent,
    PublicResponse,
)

__all__ = [
    "ACTION_NOT_ENABLED",
    "CognitiveAction",
    "CognitiveActionType",
    "CognitiveState",
    "CommunicationPlan",
    "InputEvent",
    "PublicResponse",
]
