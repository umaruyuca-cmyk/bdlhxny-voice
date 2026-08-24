"""Checkpointer 与 interrupt/resume 的统一配置工具。"""

from __future__ import annotations

from typing import Any

from .context import RunContext


def graph_config(context: RunContext) -> dict[str, Any]:
    """生成 LangGraph 配置，确保恢复时始终使用同一个 thread_id。"""

    return {
        "configurable": {
            "thread_id": context.thread_id,
            "run_id": context.run_id,
            "user_id": context.user_id,
            "tenant_id": context.tenant_id,
        }
    }
