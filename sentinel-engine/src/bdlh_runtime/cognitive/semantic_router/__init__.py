"""内核语义路由：高置信快路径分流；未命中交给 Agent 循环。"""

from .catalog import build_kernel_router
from .contracts import Route, RouteChoice, RouteDisposition
from .encoder import Encoder, EncoderUnavailableError, QwenEmbeddingEncoder
from .fastpath_data import MODEL_FASTPATH_THRESHOLDS
from .router import SemanticRouter
from .selector import SemanticRouteSelector

__all__ = [
    "Encoder",
    "EncoderUnavailableError",
    "MODEL_FASTPATH_THRESHOLDS",
    "QwenEmbeddingEncoder",
    "Route",
    "RouteChoice",
    "RouteDisposition",
    "SemanticRouteSelector",
    "SemanticRouter",
    "build_kernel_router",
]
