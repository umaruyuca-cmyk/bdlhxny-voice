"""应用装配入口。

这里只负责组装配置、Checkpointer 和 Root Graph，不包含业务节点逻辑。生产
部署时替换 Checkpointer 实现即可，不需要修改 Graph 拓扑。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stockwise_analysis.config import Settings
from stockwise_analysis.graph.root_graph import build_root_graph

from .errors import ConfigurationError


@dataclass
class StockWiseApplication:
    """封装已编译的 Root Graph 与其运行配置。"""

    settings: Settings
    graph: Any


def create_application(settings: Settings | None = None, checkpointer: Any | None = None) -> StockWiseApplication:
    """创建应用实例。

    当前默认内存 Checkpointer 仅用于本地开发和测试；生产启动时必须注入
    PostgreSQL 或 Redis 的持久化实现。
    """

    resolved_settings = settings or Settings.from_environment()
    if resolved_settings.environment == "production" and checkpointer is None:
        raise ConfigurationError(
            "production requires an injected persistent Checkpointer; InMemorySaver is development-only"
        )
    return StockWiseApplication(
        settings=resolved_settings,
        graph=build_root_graph(checkpointer=checkpointer),
    )
