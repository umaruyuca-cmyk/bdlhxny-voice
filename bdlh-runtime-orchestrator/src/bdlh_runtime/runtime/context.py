"""一次 LangGraph 运行的不可变上下文。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunContext:
    """放在配置层的身份信息，不把鉴权信息写入可展示的 Graph State。"""

    thread_id: str
    run_id: str
    user_id: str | None = None
    tenant_id: str | None = None
