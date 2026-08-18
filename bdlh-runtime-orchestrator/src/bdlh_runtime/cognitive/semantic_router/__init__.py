"""内核语义路由：高置信快路径分流，不是 Agent Brain，也不选择 Skill。

对齐 aurelio-labs/semantic-router 的 Route + utterances + 阈值模型；
未命中或低于阈值时返回 None，交给后续 Understand / Agent Loop。
"""

from .catalog import build_kernel_router, fastpath_routes_from_snapshot
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
    "fastpath_routes_from_snapshot",
]
