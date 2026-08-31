"""会话事件的统一轮次口径。"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.session.loader import SessionEvent


def events_with_turns(events: tuple[SessionEvent, ...]) -> list[dict[str, Any]]:
    """把事件映射为可展示 payload，并为每个完整对话轮分配 ``turn_id``。

    一条 user_message 开启一轮；下一条 user_message 之前的助手消息、工具调用
    和工具结果都属于这一轮。开头若存在系统产生的孤立事件，归入 ``turn-0000``，
    但冻结 Session 的正常校验数据通常从用户消息开始。
    """

    turn_number = 0
    payload: list[dict[str, Any]] = []
    for event in events:
        if event.type == "user_message":
            turn_number += 1
        turn_id = f"turn-{turn_number:04d}"
        payload.append(
            {
                "event_id": event.event_id,
                "sequence": event.seq,
                "turn_id": turn_id,
                "event_type": event.type,
                "role": event.role,
                "content": event.content,
                "occurred_at": event.occurred_at,
                "call_id": event.call_id,
                "tool_name": event.tool_name,
                "status": event.status,
                "error_code": event.error_code,
                "source_id": event.source_id,
            }
        )
    return payload
