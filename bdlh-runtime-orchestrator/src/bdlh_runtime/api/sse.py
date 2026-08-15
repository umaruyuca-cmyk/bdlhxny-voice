"""Server-Sent Events（SSE）序列化工具。"""

from __future__ import annotations

import json
from typing import Any


def encode_event(event_name: str, payload: dict[str, Any]) -> str:
    """将结构化事件编码为标准 SSE 帧。"""

    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
