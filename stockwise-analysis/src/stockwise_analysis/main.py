"""ASGI 应用入口；部署命令使用 ``stockwise_analysis.main:app``。

审查文档 §6.3：api_prefix 由 Settings 提供，应用工厂统一注册路由，
配置与实际行为一致。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from stockwise_analysis.api.routes import create_api_app
from stockwise_analysis.config import Settings
from stockwise_analysis.runtime.errors import ConfigurationError
from stockwise_analysis.runtime.application import create_application

_settings = Settings.from_environment()


def _create_app() -> FastAPI:
    """生产 PostgreSQL 使用异步 Saver；开发环境保持轻量同步装配。"""

    if _settings.environment != "production" or _settings.checkpointer_backend != "postgres":
        application = create_application(_settings)
        return create_api_app(application, api_prefix=_settings.api_prefix)

    if not _settings.postgres_dsn:
        raise ConfigurationError("生产 PostgreSQL Checkpointer 需要 POSTGRES_DSN")

    @asynccontextmanager
    async def lifespan(shell: FastAPI):
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(_settings.postgres_dsn) as checkpointer:
            await checkpointer.setup()
            application = create_application(
                _settings,
                checkpointer_override=checkpointer,
            )
            inner = create_api_app(application, api_prefix=_settings.api_prefix)
            shell.mount("/", inner)
            yield

    return FastAPI(
        title="StockWise Analysis Workflow",
        version="0.1.0",
        lifespan=lifespan,
    )


app = _create_app()

__all__ = ["app"]
