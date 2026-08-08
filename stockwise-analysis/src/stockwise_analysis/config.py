"""应用配置入口。

配置只描述运行边界，不在 Graph 节点内读取环境变量。这样测试、命令行和
未来的容器部署可以注入不同配置，而不会改变业务流程代码。
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """StockWise Python 服务的最小运行配置。"""

    environment: str = "development"
    checkpointer_backend: str = "memory"
    api_prefix: str = "/api/v1"
    max_event_wait_seconds: float = 30.0

    @classmethod
    def from_environment(cls) -> "Settings":
        """从环境变量读取配置；生产环境应由部署系统统一注入。"""

        return cls(
            environment=os.getenv("STOCKWISE_ENV", "development"),
            checkpointer_backend=os.getenv("STOCKWISE_CHECKPOINTER_BACKEND", "memory"),
            api_prefix=os.getenv("STOCKWISE_API_PREFIX", "/api/v1"),
            max_event_wait_seconds=float(os.getenv("STOCKWISE_MAX_EVENT_WAIT_SECONDS", "30")),
        )
