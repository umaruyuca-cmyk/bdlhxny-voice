from __future__ import annotations

import json
import re
from typing import Protocol

from .models import ContextItem
from .summary import HistorySummarizer
from .token_count import TokenCounter


class ContextCompressor(Protocol):
    def compress(self, item: ContextItem, max_tokens: int, counter: TokenCounter) -> str: ...


class SummarizerCompressor:
    """budgeted 压缩的生成式变体:被压缩条目的替代文本由摘要器生成。

    - 摘要器(LLMSummarizer)返回非空且不同于原文时采用——即"LLM 生成式压缩";
    - 返回空或与原文相同时回退内层结构化抽取,不编造、不超出预算语义;
    - LLM 不可用/调用失败/超预算的降级事件由摘要器记入 usage.warnings,
      经编译器写入工件 warnings(诚实标注,不冒充生成成功)。
    """

    def __init__(self, summarizer: HistorySummarizer, inner: ContextCompressor | None = None) -> None:
        self._summarizer = summarizer
        self._inner = inner or StructuredTextCompressor()

    def compress(self, item: ContextItem, max_tokens: int, counter: TokenCounter) -> str:
        summary = self._summarizer.summarize([item.content], max_tokens, counter)
        text = (summary or "").strip()
        if text and text != item.content.strip():
            return text
        return self._inner.compress(item, max_tokens, counter)


class StructuredTextCompressor:
    """Deterministic compression with explicit omission and source markers."""

    _blank_lines = re.compile(r"\n\s*\n+")
    _spaces = re.compile(r"[ \t]+")

    def compress(self, item: ContextItem, max_tokens: int, counter: TokenCounter) -> str:
        if max_tokens <= 0:
            return ""

        normalized = self._normalize(item.content)
        compact_json = self._compact_json(normalized)
        if compact_json is not None:
            normalized = compact_json

        if counter.count(normalized) <= max_tokens:
            return normalized

        source = item.source_id or item.item_id
        marker = f"[compressed source={source}]"
        if counter.count(marker) >= max_tokens:
            return self._fit(marker, max_tokens, counter)

        available = max_tokens - counter.count(marker)
        head_size = max(1, int(len(normalized) * 0.6))
        tail_size = max(1, int(len(normalized) * 0.25))
        candidate = f"{marker}\n{normalized[:head_size]}\n[content omitted]\n{normalized[-tail_size:]}"

        while counter.count(candidate) > max_tokens and (head_size > 1 or tail_size > 1):
            if head_size >= tail_size and head_size > 1:
                head_size = max(1, int(head_size * 0.8))
            elif tail_size > 1:
                tail_size = max(1, int(tail_size * 0.8))
            candidate = f"{marker}\n{normalized[:head_size]}\n[content omitted]\n{normalized[-tail_size:]}"

        if counter.count(candidate) <= max_tokens:
            return candidate

        return self._fit(f"{marker}\n{normalized}", max_tokens, counter, available)

    def _normalize(self, content: str) -> str:
        paragraphs = []
        seen = set()
        for paragraph in self._blank_lines.split(content.strip()):
            cleaned = self._spaces.sub(" ", paragraph).strip()
            if cleaned and cleaned not in seen:
                paragraphs.append(cleaned)
                seen.add(cleaned)
        return "\n\n".join(paragraphs)

    @staticmethod
    def _compact_json(content: str) -> str | None:
        if not content.startswith(("{", "[")):
            return None
        try:
            value = json.loads(content)
        except json.JSONDecodeError:
            return None
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _fit(text: str, max_tokens: int, counter: TokenCounter, initial_size: int | None = None) -> str:
        if counter.count(text) <= max_tokens:
            return text
        low = 0
        high = min(len(text), initial_size or len(text))
        while low < high:
            middle = (low + high + 1) // 2
            if counter.count(text[:middle]) <= max_tokens:
                low = middle
            else:
                high = middle - 1
        return text[:low]
