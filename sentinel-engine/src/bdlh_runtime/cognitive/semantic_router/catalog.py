"""内核快路径路由：只做分流，不出现任何 Domain / Skill 名称。

样句真源是 ``fastpath_data.py``（非 Registry 八表）。词法编码用样句文件里的
默认阈值；Qwen 向量模型编码必须传 ``MODEL_FASTPATH_THRESHOLDS``（相似度空间不同）。
"""

from __future__ import annotations

from collections.abc import Mapping

from .contracts import Route, RouteDisposition
from .encoder import Encoder
from .fastpath_data import FASTPATH_ROUTES
from .router import SemanticRouter


def fastpath_routes(*, score_thresholds: Mapping[str, float] | None = None) -> list[Route]:
    dispositions = {"RESPOND": RouteDisposition.RESPOND, "BLOCK": RouteDisposition.BLOCK}
    return [
        Route(
            name=item.name,
            score_threshold=(
                score_thresholds[item.name]
                if score_thresholds is not None and item.name in score_thresholds
                else item.score_threshold
            ),
            disposition=dispositions[item.disposition],
            response=item.response,
            utterances=item.utterances,
        )
        for item in FASTPATH_ROUTES
    ]


def build_kernel_router(
    *,
    encoder: Encoder,
    score_thresholds: Mapping[str, float] | None = None,
) -> SemanticRouter:
    """装配内核语义路由（样句来自 fastpath_data）。"""
    return SemanticRouter(fastpath_routes(score_thresholds=score_thresholds), encoder=encoder)
