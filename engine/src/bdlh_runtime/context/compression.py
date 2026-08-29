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

    - 优先消费编译器预生成的冻结摘要映射(``set_summary_map``):
      构建阶段零网络调用,映射内条目不再逐条请求模型;
    - 无映射(或映射未覆盖该条目)时回退到逐条摘要路径——该路径只在
      未启用批量预处理的调用方(如直接注入的单测)出现;
    - 摘要非空、不同于原文且不超预算时采用;否则回退内层结构化抽取;
    - LLM 不可用/调用失败/超预算的降级事件由摘要器记入 usage.warnings,
      经编译器写入工件 warnings(诚实标注,不冒充生成成功)。
    """

    def __init__(self, summarizer: HistorySummarizer, inner: ContextCompressor | None = None) -> None:
        self._summarizer = summarizer
        self._inner = inner or StructuredTextCompressor()
        self._summary_map: dict[str, str] | None = None

    def set_summary_map(self, mapping: dict[str, str]) -> None:
        """注入预生成的 item_id → 摘要冻结映射(批量分块摘要的产物)。"""

        self._summary_map = dict(mapping)

    def compress(self, item: ContextItem, max_tokens: int, counter: TokenCounter) -> str:
        if self._summary_map is not None:
            # 冻结映射已注入:构建阶段零网络调用;未覆盖/超预算条目直接抽取式回退
            text = (self._summary_map.get(item.item_id) or "").strip()
            if text and text != item.content.strip() and counter.count(text) <= max_tokens:
                return text
            return self._inner.compress(item, max_tokens, counter)
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
