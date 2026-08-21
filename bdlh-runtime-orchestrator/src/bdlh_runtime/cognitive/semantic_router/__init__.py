"""内核语义路由：高置信快路径分流；未命中交给 Understand / GoalAction。"""

from .catalog import build_kernel_router
from .contracts import Route, RouteChoice, RouteDisposition
from .encoder import Encoder, LexicalEncoder
from .router import SemanticRouter
from .selector import SemanticRouteSelector

__all__ = [
    "Encoder",
    "LexicalEncoder",
    "Route",
    "RouteChoice",
    "RouteDisposition",
    "SemanticRouteSelector",
    "SemanticRouter",
    "build_kernel_router",
]
