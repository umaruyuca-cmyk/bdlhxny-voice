"""ASGI 应用入口；部署命令使用 ``bdlh_runtime.main:app``。

审查文档 §6.3：api_prefix 由 Settings 提供，应用工厂统一注册路由，
配置与实际行为一致。
"""

from __future__ import annotations

from fastapi import FastAPI

from bdlh_runtime.api.routes import create_api_app
from bdlh_runtime.config import Settings
from bdlh_runtime.runtime.application import create_application

_settings = Settings.from_environment()


def _create_app() -> FastAPI:
    """创建仅依赖 Java Data Plane 的 ASGI 应用。"""

    application = create_application(_settings)
    return create_api_app(application, api_prefix=_settings.api_prefix)


app = _create_app()

__all__ = ["app"]
