"""认知内核：契约与受控编排（产品唯一主路径）。"""

from .contracts import (
    ACTION_NOT_ENABLED,
    RESPOND_UNAVAILABLE_REASON,
    CognitiveAction,
    CognitiveActionSummary,
    CognitiveActionType,
    CognitiveState,
    CommunicationPlan,
    CommunicationSection,
    InputEvent,
    InputEventType,
    PublicResponse,
)
from .goal_action_selector import GoalActionSelector
from .plugin_gates import SkillCatalog, SkillToolSpec
from .policy import ActionPolicyResult, DefaultActionPolicy
from .semantic_router import (
    Route,
    RouteChoice,
    SemanticRouter,
    SemanticRouteSelector,
    build_kernel_router,
)

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
    "GoalActionSelector",
    "InputEvent",
    "InputEventType",
    "PublicResponse",
    "RESPOND_UNAVAILABLE_REASON",
    "Route",
    "RouteChoice",
    "SemanticRouteSelector",
    "SemanticRouter",
    "SkillCatalog",
    "SkillToolSpec",
    "build_kernel_router",
]
