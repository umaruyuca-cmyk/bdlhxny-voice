"""SemanticRouter：对每条 Route 取示例最大余弦，过阈值才命中。

未过任何阈值时返回 None，这是进入 Understand / Agent Loop 的默认路径。
"""

from __future__ import annotations

from .contracts import Route, RouteChoice
from .encoder import Encoder, LexicalEncoder


class SemanticRouter:
    """用示例话语做超快分类；不调用 LLM，也不选择 Skill。"""

    def __init__(
        self,
        routes: list[Route],
        *,
        encoder: Encoder | None = None,
    ) -> None:
        if not routes:
            raise ValueError("routes must not be empty")
        names = [route.name for route in routes]
        if len(names) != len(set(names)):
            raise ValueError("route names must be unique")
        self._routes = tuple(routes)
        self._encoder = encoder or LexicalEncoder()
        # 1. 启动时预编码全部 utterance，查询时只编码用户一句话。
        self._index: dict[str, list[list[float]]] = {}
        for route in self._routes:
            self._index[route.name] = self._encoder.encode(list(route.utterances))

    def __call__(self, text: str) -> RouteChoice | None:
        return self.route(text)

    def route(self, text: str) -> RouteChoice | None:
        query = (text or "").strip()
        if not query:
            return None
        # 1. 编码查询，对每条 Route 取与其 utterance 的最大余弦。
        query_vec = self._encoder.encode([query])[0]
        scores: dict[str, float] = {}
        for route in self._routes:
            scores[route.name] = max(
                _dot(query_vec, utterance) for utterance in self._index[route.name]
            )
        # 2. 只保留过自身阈值的候选；都不过则走 Agent。
        passing = [
            route
            for route in self._routes
            if scores[route.name] >= route.score_threshold
        ]
        if not passing:
            return None
        winner = max(passing, key=lambda route: scores[route.name])
        return RouteChoice(
            name=winner.name,
            similarity=scores[winner.name],
            disposition=winner.disposition,
            response=winner.response,
            scores=scores,
        )


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))
