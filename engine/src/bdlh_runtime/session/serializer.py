"""Session 事件 → ContextItem 序列化(不读取 gold)。

转换规则:
- ``user_message`` / ``assistant_message`` → conversation 条目,保持对话消息
  形态与顺序,可被四种策略统一选择/压缩;
- ``tool_call`` + 紧随的 ``tool_result`` → 合并为**一条**不可信数据条目
  (调用与结果不可拆开),工具返回按不可信数据处理;
- 事件正文不带任何评测标注(gold 里的 classification/priority 不会进入这里)。

budgeted 策略使用的 priority 是确定性启发(用户消息 > 助手消息 > 工具结果),
属于 structured-text-v1 早期实现的一部分,不是文档中的多因子重要度。

序列化末尾统一补引用元数据(公式五因子输入):
- ``superseded``:同 source_id 的条目出现更晚 observed_at 时,旧条标记为已取代
  (staleness/source_quality 因子输入;时间相同取更晚 sequence 者为最新);
- ``cited_by``:条目 source_id 指向另一条目 item_id 时建立反向引用
  (citation_dependency 因子输入;确定性排序,同输入同输出)。
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass

from bdlh_runtime.context import ContextClassification, ContextItem, ContextRole

from .loader import SessionCase, SessionEvent

#: budgeted 早期实现的确定性启发优先级(非多因子公式)
PRIORITY_USER_MESSAGE = 10
PRIORITY_ASSISTANT_MESSAGE = 5
PRIORITY_TOOL_PAIR = 3


@dataclass(frozen=True)
class SerializedItem:
    """一个条目及其覆盖的原始事件 id(工具对覆盖 call+result 两个事件)。"""

    item: ContextItem
    event_ids: tuple[str, ...]


def serialize_session(session: SessionCase) -> tuple[SerializedItem, ...]:
    """把有序事件流转换为构建器条目;配对错误在 loader 阶段已拦截。"""

    serialized: list[SerializedItem] = []
    index = 0
    events = session.events
    while index < len(events):
        event = events[index]
        if event.type == "tool_call":
            paired_result = events[index + 1] if index + 1 < len(events) else None
            if paired_result is None or paired_result.type != "tool_result":
                raise ValueError(f"tool_call {event.event_id} 缺少紧邻结果(loader 校验应已拦截)")
            serialized.append(_tool_pair_item(event, paired_result))
            index += 2
            continue
        serialized.append(_message_item(event))
        index += 1
    return tuple(_apply_reference_metadata(serialized))


def _apply_reference_metadata(serialized: list[SerializedItem]) -> list[SerializedItem]:
    """补 superseded 与 cited_by;两者都只来自条目自带元数据,确定性计算。"""

    items = [entry.item for entry in serialized]
    item_ids = {item.item_id for item in items}

    # 同 source_id 的最新版本:(observed_at, sequence) 字典序最大者胜
    latest_by_source: dict[str, tuple[str, int]] = {}
    for item in items:
        if not item.source_id:
            continue
        version = (item.observed_at or "", item.sequence)
        current = latest_by_source.get(item.source_id)
        if current is None or version > current:
            latest_by_source[item.source_id] = version

    # 反向引用:条目 source_id 指向另一条目 item_id → 被指条目获得 cited_by
    cited_by: dict[str, list[str]] = {}
    for item in items:
        target = item.source_id
        if target and target != item.item_id and target in item_ids:
            cited_by.setdefault(target, []).append(item.item_id)

    result: list[SerializedItem] = []
    for entry in serialized:
        item = entry.item
        superseded = False
        if item.source_id and item.source_id in latest_by_source:
            superseded = (item.observed_at or "", item.sequence) < latest_by_source[item.source_id]
        references = tuple(sorted(cited_by.get(item.item_id, [])))
        if superseded != item.superseded or references != item.cited_by:
            item = dataclasses.replace(item, superseded=superseded, cited_by=references)
        result.append(SerializedItem(item=item, event_ids=entry.event_ids))
    return result


def _message_item(event: SessionEvent) -> SerializedItem:
    assistant = event.type == "assistant_message"
    return SerializedItem(
        item=ContextItem(
            item_id=event.event_id,
            content=event.content,
            classification=ContextClassification.COMPRESSIBLE,
            role=ContextRole.ASSISTANT if assistant else ContextRole.USER_DATA,
            priority=PRIORITY_ASSISTANT_MESSAGE if assistant else PRIORITY_USER_MESSAGE,
            source_id=event.source_id or event.event_id,
            observed_at=event.occurred_at or None,
            sequence=event.seq,
            conversation=True,
        ),
        event_ids=(event.event_id,),
    )


def _tool_pair_item(call: SessionEvent, result: SessionEvent) -> SerializedItem:
    rendered_args = json.dumps(call.arguments or {}, ensure_ascii=False, sort_keys=True)
    status = result.status or "success"
    lines = [
        f"tool_call {call.tool_name}({rendered_args})",
        f"tool_result({status}){f' error_code={result.error_code}' if result.error_code else ''}:",
        result.content,
    ]
    return SerializedItem(
        item=ContextItem(
            item_id=call.event_id,
            content="\n".join(lines),
            classification=ContextClassification.COMPRESSIBLE,
            role=ContextRole.UNTRUSTED_DATA,
            priority=PRIORITY_TOOL_PAIR,
            source_id=call.source_id or call.event_id,
            observed_at=result.occurred_at or call.occurred_at or None,
            sequence=call.seq,
            trusted=False,
        ),
        event_ids=(call.event_id, result.event_id),
    )
