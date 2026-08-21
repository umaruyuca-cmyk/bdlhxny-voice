"""内核快路径路由：只做分流，不出现任何 Domain / Skill 名称。

样句真源是 ``fastpath_data.py``（非 Registry 八表）。
"""

from __future__ import annotations

from .contracts import Route, RouteDisposition
from .encoder import Encoder
from .fastpath_data import FASTPATH_ROUTES
from .router import SemanticRouter


def fastpath_routes() -> list[Route]:
    dispositions = {"RESPOND": RouteDisposition.RESPOND, "BLOCK": RouteDisposition.BLOCK}
    return [
        Route(
            name=item.name,
            score_threshold=item.score_threshold,
            disposition=dispositions[item.disposition],
            response=item.response,
            utterances=item.utterances,
        )
        for item in FASTPATH_ROUTES
    ]


def build_kernel_router(*, encoder: Encoder | None = None) -> SemanticRouter:
    """装配内核语义路由（样句来自 fastpath_data）。"""
    return SemanticRouter(fastpath_routes(), encoder=encoder)
