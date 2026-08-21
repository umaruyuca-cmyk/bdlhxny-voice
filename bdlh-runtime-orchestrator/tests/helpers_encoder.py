"""Tests-only lexical encoder — not a product path.

Stable hashed n-gram vectors for offline semantic-router unit tests.
"""

from __future__ import annotations

import hashlib
import math
import re


class LexicalEncoder:
    """字符 n-gram + 词元的哈希向量，用余弦即可比较语义相近的短句。"""

    def __init__(self, *, dim: int = 384, ngram_min: int = 2, ngram_max: int = 3) -> None:
        if dim < 32:
            raise ValueError("dim must be >= 32")
        if ngram_min < 1 or ngram_max < ngram_min:
            raise ValueError("invalid n-gram range")
        self._dim = dim
        self._ngram_min = ngram_min
        self._ngram_max = ngram_max

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [_l2_normalize(self._vector(text)) for text in texts]

    def _vector(self, text: str) -> list[float]:
        normalized = _normalize(text)
        vector = [0.0] * self._dim
        if not normalized:
            return vector
        for n in range(self._ngram_min, self._ngram_max + 1):
            if len(normalized) < n:
                continue
            for i in range(len(normalized) - n + 1):
                vector[self._bucket(normalized[i : i + n])] += 1.0
        for token in _TOKEN_RE.findall(normalized):
            if len(token) >= 2:
                vector[self._bucket(f"tok:{token}")] += 2.0
        return vector

    def _bucket(self, gram: str) -> int:
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, "big") % self._dim


_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]
