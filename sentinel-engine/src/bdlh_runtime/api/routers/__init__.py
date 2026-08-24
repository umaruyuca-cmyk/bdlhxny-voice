"""API router 按资源拆分（重构方案 D1/P3）。

每个模块提供 ``register(router, ctx)``，由 ``api.routes.create_api_app``
统一装配；模块内不直接依赖应用工厂。
"""

from __future__ import annotations

from . import agent_runs, chat, conversations, financial_tasks, notifications

__all__ = [
    "agent_runs",
    "chat",
    "conversations",
    "financial_tasks",
    "notifications",
]
