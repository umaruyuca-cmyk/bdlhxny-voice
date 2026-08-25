"""Server-Sent Events（SSE）序列化工具。"""

from __future__ import annotations

import json
from typing import Any


def encode_event(event_name: str, payload: dict[str, Any]) -> str:
    """将结构化事件编码为标准 SSE 帧。"""

    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def encode_token(content: str) -> str:
    """``token`` 文本分片（LLM ``astream`` 增量，禁止定长切片）。"""

    return encode_event(
        "message",
        {"schema_version": "1.0", "type": "token", "content": content},
    )


def encode_tool_step(
    *,
    tool: str,
    arguments: dict[str, Any],
    status: str,
    **extra: Any,
) -> str:
    """``tool.step``：工具调用实时外显（含 ``search_tools``）。"""

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "type": "tool.step",
        "tool": tool,
        "arguments": arguments,
        "status": status,
    }
    for key, value in extra.items():
        if value is not None:
            payload[key] = value
    return encode_event("message", payload)
