"""工具检索索引（设计文档 §4.2 search 策略）。

``search_tools(query, top_k)`` 是 search 装载模式的元工具：对**权限过滤后**的
目录做 embedding 相似度检索（top-k + 阈值），命中 ToolCard 动态装载。
编码器复用 ``engine.semantic_router.encoder.Encoder``。
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence

from bdlh_runtime.engine.semantic_router.encoder import Encoder, EncoderUnavailableError
from bdlh_runtime.tools.catalog import ToolCard

logger = logging.getLogger("bdlh_runtime.tools.search")

SEARCH_TOOLS_NAME = "search_tools"
DEFAULT_TOP_K = 3
DEFAULT_SIMILARITY_THRESHOLD = 0.28
MISS_FALLBACK_LIMIT = 2


class ToolSearchIndex:
    """对可见 ToolCard 做 embedding 检索；权限过滤由调用方先完成。"""

    def __init__(
        self,
        encoder: Encoder,
        *,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> None:
        self._encoder = encoder
        self._threshold = similarity_threshold

    def search(
        self,
        query: str,
        visible: Sequence[ToolCard],
        *,
        top_k: int = DEFAULT_TOP_K,
    ) -> list[ToolCard]:
        """兼容面:返回命中工具卡(按分数降序)。"""
        return [card for _score, card in self.search_scored(query, visible, top_k=top_k)]

    def search_scored(
        self,
        query: str,
        visible: Sequence[ToolCard],
        *,
        top_k: int = DEFAULT_TOP_K,
    ) -> list[tuple[float, ToolCard]]:
        """带分数检索:(相似度, 工具卡) 按分数降序;排名与分数供工件归因(C3)。"""
        text = (query or "").strip()
        candidates = [card for card in visible if card.name != SEARCH_TOOLS_NAME]
        if not text or not candidates or top_k <= 0:
            return []
        documents_full = [_full_document(card) for card in candidates]
        documents_keywords = [_keyword_document(card) for card in candidates]
        try:
            vectors = self._encoder.encode([text, *documents_full, *documents_keywords])
        except EncoderUnavailableError as exc:
            logger.warning("tool_search_encoder_unavailable degrade=miss reason=%s", exc)
            return []
        if not vectors or not vectors[0]:
            return []
        query_vec = vectors[0]
        count = len(candidates)
        full_vectors = vectors[1 : 1 + count]
        keyword_vectors = vectors[1 + count : 1 + 2 * count]
        if len(full_vectors) != count or len(keyword_vectors) != count:
            return []
        scored: list[tuple[float, ToolCard]] = []
        for card, full_vec, keyword_vec in zip(candidates, full_vectors, keyword_vectors, strict=True):
            score = max(_cosine(query_vec, full_vec), _cosine(query_vec, keyword_vec))
            if score >= self._threshold:
                scored.append((score, card))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[:top_k]

    @property
    def threshold(self) -> float:
        return self._threshold


def _full_document(card: ToolCard) -> str:
    return f"{card.name} {card.description}"


def _keyword_document(card: ToolCard) -> str:
    """双目的 description 的检索关键词段；短查询对整段描述会被长尾 n-gram 稀释。"""
    description = card.description or ""
    marker = "检索关键词"
    if marker in description:
        description = description.split(marker, 1)[1].lstrip("：: ")
    return description.strip() or card.name


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    if norm == 0.0:
        return 0.0
    return dot / norm
