"""single-summary 策略的独立摘要基准。

与自研 ``StructuredTextCompressor``(budgeted 策略使用)严格分离:
- 不读取条目 priority、classification 之外的任何评分信号;
- 不使用头尾保留+二分截断的规则裁剪;
- 不读取 gold,不依赖 budgeted 策略的选择结果。

默认实现 ``ExtractiveSummarizer`` 是确定性抽取式摘要:把预算均匀分配给
每条输入文本,按句子边界从头填充。有真实模型时可注入 ``summarize`` 面更
强的实现(如一次性 LLM 摘要),摘要的 Token/时长/成本由调用方单独记录。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

from .token_count import TokenCounter

EXTRACTIVE_SUMMARIZER_VERSION = "extractive-uniform-v1"

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")


class HistorySummarizer(Protocol):
    """一次性历史摘要基准面:多段文本 + 预算 → 一段摘要。"""

    version: str

    def summarize(self, texts: Sequence[str], max_tokens: int, counter: TokenCounter) -> str: ...


class ExtractiveSummarizer:
    """均匀分配预算的抽取式摘要(独立基准,无模型依赖)。"""

    def __init__(self, version: str = EXTRACTIVE_SUMMARIZER_VERSION) -> None:
        self.version = version

    def summarize(self, texts: Sequence[str], max_tokens: int, counter: TokenCounter) -> str:
        usable = [text.strip() for text in texts if text and text.strip()]
        if not usable or max_tokens <= 0:
            return ""
        header = f"[history-summary method={self.version} items={len(usable)}]"
        budget = max_tokens - counter.count(header)
        if budget <= 0:
            return header
        share = budget // len(usable)
        parts: list[str] = []
        used = 0
        for index, text in enumerate(usable):
            # 余数给最后一段,保证预算用满且分配确定
            allowance = share + (budget - share * len(usable) if index == len(usable) - 1 else 0)
            if allowance <= 0:
                continue
            part = self._leading_sentences(text, allowance, counter)
            if not part:
                continue
            parts.append(part)
            used += counter.count(part)
            if used >= budget:
                break
        if not parts:
            return header
        return f"{header}\n" + "\n".join(parts)

    @staticmethod
    def _leading_sentences(text: str, max_tokens: int, counter: TokenCounter) -> str:
        """从头按完整句子填充,不截断半句(与规则裁剪的头尾拼接明确不同)。"""
        taken: list[str] = []
        used = 0
        for sentence in _SENTENCE_SPLIT.split(text):
            if not sentence.strip():
                continue
            tokens = counter.count(sentence)
            if used + tokens > max_tokens:
                if not taken and tokens > max_tokens:
                    # 单句超预算:保留该句能放下的完整前缀不再细切,直接跳过
                    continue
                break
            taken.append(sentence)
            used += tokens
        return "".join(taken).strip()
