"""Checkpointer 工厂（审查文档 §4.3）。

按配置创建 LangGraph Checkpointer：
- memory：InMemorySaver（开发/测试）；
- postgres：PostgresSaver（生产，依赖 psycopg/pgvector 可选组）；
- redis：RedisSaver（生产，依赖 langgraph-checkpoint-redis 可选组）。

生产环境（settings.environment == "production"）必须使用持久化后端，
不允许静默退化到内存。依赖未安装时抛 ConfigurationError，而不是降级——
因为生产环境丢失状态比启动失败更危险。
"""

from __future__ import annotations

import logging
from typing import Any

from bdlh_runtime.config import Settings

from .errors import ConfigurationError

logger = logging.getLogger("bdlh_runtime.runtime.checkpointers")


def create_checkpointer(settings: Settings) -> Any:
    """按配置创建 Checkpointer 实例。

    规则：
    - 显式 ``postgres`` / ``redis`` 按配置创建；
    - 配置了 ``POSTGRES_DSN`` 且后端仍为默认 ``memory`` 时，自动改用 PostgreSQL
      （云上联调/部署与业务 Store 保持同一持久化后端）；
    - 生产环境禁止最终落在 memory。
    """
    backend = settings.checkpointer_backend
    if backend == "memory" and settings.postgres_dsn:
        logger.info(
            "已配置 POSTGRES_DSN，Checkpointer 自动使用 postgres 后端"
        )
        backend = "postgres"

    if backend == "memory":
        if settings.environment == "production":
            raise ConfigurationError(
                "生产环境不允许使用 memory Checkpointer，请配置 PostgreSQL 或 Redis 后端。"
            )
        return _create_memory_checkpointer()

    if backend == "postgres":
        return _create_postgres_checkpointer(settings)

    if backend == "redis":
        return _create_redis_checkpointer(settings)

    raise ConfigurationError(f"未知的 Checkpointer 后端: {backend}")


def _create_memory_checkpointer() -> Any:
    """开发环境的内存 Checkpointer。"""
    try:
        from langgraph.checkpoint.memory import InMemorySaver
    except ImportError:
        from langgraph.checkpoint.memory import MemorySaver as InMemorySaver
    return InMemorySaver()


def _create_postgres_checkpointer(settings: Settings) -> Any:
    """PostgreSQL Checkpointer（生产）。"""
    # 需要环境变量提供连接串；未配置或依赖缺失都抛错（生产不降级）
    dsn = getattr(settings, "postgres_dsn", None) or _env("POSTGRES_DSN")
    if not dsn:
        raise ConfigurationError("postgres Checkpointer 需要 POSTGRES_DSN 环境变量")
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg import Connection

        conn = Connection.connect(dsn)
        checkpointer = PostgresSaver(conn)
        checkpointer.setup()  # 初始化表结构
        return checkpointer
    except ImportError as exc:
        raise ConfigurationError(
            "postgres Checkpointer 需要安装可选依赖: "
            "pip install 'langgraph-checkpoint-postgres' psycopg[binary]"
        ) from exc
    except Exception as exc:
        raise ConfigurationError(f"PostgreSQL Checkpointer 初始化失败: {exc}") from exc


def _create_redis_checkpointer(settings: Settings) -> Any:
    """Redis Checkpointer（生产）。"""
    url = getattr(settings, "redis_url", None) or _env("REDIS_URL")
    if not url:
        raise ConfigurationError("redis Checkpointer 需要 REDIS_URL 环境变量")
    try:
        from langgraph.checkpoint.redis import RedisSaver
        from redis import Redis

        client = Redis.from_url(url)
        checkpointer = RedisSaver(client)
        checkpointer.setup()
        return checkpointer
    except ImportError as exc:
        raise ConfigurationError(
            "redis Checkpointer 需要安装可选依赖: pip install 'langgraph-checkpoint-redis' redis"
        ) from exc
    except Exception as exc:
        raise ConfigurationError(f"Redis Checkpointer 初始化失败: {exc}") from exc


def _env(name: str) -> str | None:
    import os
    return os.getenv(name)
