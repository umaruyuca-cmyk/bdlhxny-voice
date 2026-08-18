"""内核快路径路由：只做分流，不出现任何 Domain / Skill 名称。

路由真源是库表 ``bdlh_runtime_fastpath_*``（经 RegistrySnapshot 加载）；
``kernel_routes()`` 硬编码已删除（重写 §6.1）。
"""

from __future__ import annotations

from .contracts import Route, RouteDisposition
from .encoder import Encoder
from .router import SemanticRouter


def fastpath_routes_from_snapshot(snapshot) -> list[Route]:
    """从已通过启动校验的快照构建 Route（DB 真源）。"""
    dispositions = {"RESPOND": RouteDisposition.RESPOND, "BLOCK": RouteDisposition.BLOCK}
    routes = []
    for record in sorted(snapshot.fastpath_routes, key=lambda item: item.name):
        routes.append(Route(
            name=record.name,
            score_threshold=record.score_threshold,
            disposition=dispositions[record.disposition],
            response=record.response,
            utterances=record.utterances,
        ))
    return routes


def build_kernel_router(*, snapshot=None, encoder: Encoder | None = None) -> SemanticRouter:
    """装配内核语义路由；snapshot 必须显式注入（禁止内置样句兜底）。"""
    if snapshot is None:
        raise ValueError("build_kernel_router requires a registry snapshot (fastpath routes come from DB)")
    return SemanticRouter(fastpath_routes_from_snapshot(snapshot), encoder=encoder)
