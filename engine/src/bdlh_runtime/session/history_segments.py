"""历史 Segment → 序列化条目的纯替换(Compiler 注入,不访问 Data Service)。

输入是已冻结的整轮 Segment 与当前 Session 的序列化条目;输出把被完整
覆盖的连续条目替换为一个合成摘要条目。任何不合法(事件不连续、部分
覆盖、与其他 Segment 重叠、摘要为空)都只拒绝注入并记录 warning,
原始条目保持原文——注入失败永远不删除历史。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from bdlh_runtime.context import ContextClassification, ContextItem, ContextRole

from .serializer import SerializedItem


class HistorySegmentLike(Protocol):
    """Compiler 消费 Segment 的结构契约(MemorySegment 满足)。"""

    @property
    def segment_id(self) -> str: ...

    @property
    def summary_content(self) -> str: ...

    @property
    def source_event_ids(self) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class SegmentUsage:
    """构建结果中的 Segment 计数快照(与 SegmentPreparation 对齐)。"""

    cache_hits: int = 0
    generated: int = 0
    invalidated: int = 0


@dataclass(frozen=True)
class SegmentInjection:
    """注入结果:替换后的条目序列与实际注入的 Segment/条目 ID。"""

    items: tuple[SerializedItem, ...]
    injected_segment_ids: tuple[str, ...]
    #: 已是摘要的合成条目 id;不得再进入摘要 LLM 候选
    precompressed_item_ids: tuple[str, ...]
    warnings: tuple[str, ...]


def inject_history_segments(
    serialized: tuple[SerializedItem, ...],
    segments: Iterable[HistorySegmentLike],
) -> SegmentInjection:
    """把整轮 Segment 替换进序列化条目;非法 Segment 拒绝注入并保留原文。"""

    warnings: list[str] = []
    item_index_by_event: dict[str, int] = {}
    for index, entry in enumerate(serialized):
        for event_id in entry.event_ids:
            item_index_by_event[event_id] = index

    def position(segment: HistorySegmentLike) -> int:
        ids = list(segment.source_event_ids or ())
        if not ids:
            return len(serialized)
        return item_index_by_event.get(ids[0], len(serialized))

    ordered = sorted(enumerate(segments), key=lambda pair: (position(pair[1]), pair[0]))

    replacements: dict[int, SerializedItem] = {}
    consumed: set[int] = set()
    injected: list[str] = []
    precompressed: list[str] = []
    for fallback_index, segment in ordered:
        label = str(getattr(segment, "segment_id", "") or f"#{fallback_index}")
        ids = [str(value) for value in (segment.source_event_ids or ())]
        summary = str(segment.summary_content or "").strip()
        if not ids:
            warnings.append(f"segment {label} 缺少 source_event_ids,拒绝注入,保留原文")
            continue
        if not summary:
            warnings.append(f"segment {label} 摘要为空,拒绝注入,保留原文")
            continue
        if any(event_id not in item_index_by_event for event_id in ids):
            warnings.append(f"segment {label} 的事件不在当前 Session,拒绝注入,保留原文")
            continue
        indices = [item_index_by_event[event_id] for event_id in ids]
        span: list[int] = []
        for index in indices:
            if not span or span[-1] != index:
                span.append(index)
        contiguous = all(span[position + 1] == span[position] + 1 for position in range(len(span) - 1))
        covered: list[str] = []
        for index in span:
            covered.extend(serialized[index].event_ids)
        # 事件必须连续匹配,且条目集合恰好等于 Segment 覆盖范围(不部分覆盖)
        if not contiguous or covered != ids:
            warnings.append(f"segment {label} 未连续完整覆盖当前 Session 的整轮条目,拒绝注入,保留原文")
            continue
        if any(index in consumed for index in span):
            warnings.append(f"segment {label} 与其他 Segment 重叠,拒绝注入,保留原文")
            continue
        first = serialized[span[0]]
        synthetic = SerializedItem(
            item=ContextItem(
                item_id=f"memory-segment:{segment.segment_id}",
                content=summary,
                classification=ContextClassification.COMPRESSIBLE,
                role=ContextRole.UNTRUSTED_DATA,
                priority=first.item.priority,
                source_id=str(segment.segment_id),
                observed_at=first.item.observed_at,
                sequence=first.item.sequence,
                trusted=False,
            ),
            # 保留原始事件 ID:最终决策仍可追溯到原始历史
            event_ids=tuple(ids),
        )
        for index in span:
            replacements[index] = synthetic
            consumed.add(index)
        injected.append(str(segment.segment_id))
        precompressed.append(synthetic.item.item_id)

    if not replacements:
        return SegmentInjection(serialized, (), (), tuple(warnings))
    # 合成条目只保留每个位置一次(replacements 已按 index 去重),整体重排序列表
    merged: list[SerializedItem] = []
    emitted_synthetic: set[str] = set()
    for index, entry in enumerate(serialized):
        replacement = replacements.get(index)
        if replacement is not None:
            if replacement.item.item_id not in emitted_synthetic:
                merged.append(replacement)
                emitted_synthetic.add(replacement.item.item_id)
            continue
        merged.append(entry)
    return SegmentInjection(tuple(merged), tuple(injected), tuple(precompressed), tuple(warnings))
