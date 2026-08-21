"""认知内核：契约与受控编排（产品唯一主路径）。
"""

from .contracts import (
    ACTION_NOT_ENABLED,
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
from .goal_action_selector import GoalActionSelector, wants_finance_plugin
from .plugin_gates import finance_skill_enabled
from .policy import ActionPolicyResult, DefaultActionPolicy
from .semantic_router import (
    LexicalEncoder,
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
    "LexicalEncoder",
    "PublicResponse",
    "Route",
    "RouteChoice",
    "SemanticRouteSelector",
    "SemanticRouter",
    "build_kernel_router",
    "finance_skill_enabled",
    "wants_finance_plugin",
]
