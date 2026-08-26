"""Agent 引擎内核：契约、checkpoint、语义快路径、循环与装载（设计文档 §4.2–§4.6）。

本包是引擎内核的唯一归属：通用运行时契约（contracts）、可恢复 checkpoint、
语义快路径（semantic_router）、Agent 循环（loop）、工具装载（loader）、
工具执行器（executor）与运行时外壳（runtime）。引擎对金融确定性计算
（compute/）与供应商适配（integrations/）零依赖，领域语义经通用契约传递。
"""

from .checkpoint import CognitiveCheckpoint, build_checkpoint, extract_checkpoint
from .contracts import (
    ACTION_NOT_ENABLED,
    RESPOND_UNAVAILABLE_REASON,
    CognitiveAction,
    CognitiveActionSummary,
    CognitiveActionType,
    CognitiveState,
    CommunicationPlan,
    CommunicationSection,
    DomainBudget,
    DomainOperation,
    DomainRequest,
    GoalSpec,
    InputEvent,
    InputEventType,
    PublicResponse,
    SuccessCriterion,
)
from .executor import CatalogToolExecutor
from .loader import SCENE_TOOLSETS, ToolLoader
from .loop import AgentLoop, AgentResult, AgentTurn
from .runtime import EngineRuntime
from .semantic_router import (
    MODEL_FASTPATH_THRESHOLDS,
    Encoder,
    EncoderUnavailableError,
    QwenEmbeddingEncoder,
    Route,
    RouteChoice,
    RouteDisposition,
    SemanticRouter,
    SemanticRouteSelector,
    build_kernel_router,
)

__all__ = [
    "ACTION_NOT_ENABLED",
    "AgentLoop",
    "AgentResult",
    "AgentTurn",
    "CatalogToolExecutor",
    "CognitiveAction",
    "CognitiveActionSummary",
    "CognitiveActionType",
    "CognitiveCheckpoint",
    "CognitiveState",
    "CommunicationPlan",
    "CommunicationSection",
    "DomainBudget",
    "DomainOperation",
    "DomainRequest",
    "EngineRuntime",
    "Encoder",
    "EncoderUnavailableError",
    "GoalSpec",
    "InputEvent",
    "InputEventType",
    "MODEL_FASTPATH_THRESHOLDS",
    "PublicResponse",
    "QwenEmbeddingEncoder",
    "RESPOND_UNAVAILABLE_REASON",
    "Route",
    "RouteChoice",
    "RouteDisposition",
    "SCENE_TOOLSETS",
    "SemanticRouteSelector",
    "SemanticRouter",
    "SuccessCriterion",
    "ToolLoader",
    "build_checkpoint",
    "build_kernel_router",
    "extract_checkpoint",
]
