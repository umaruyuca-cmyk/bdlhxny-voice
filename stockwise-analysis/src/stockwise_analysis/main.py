"""ASGI 应用入口；部署命令使用 ``stockwise_analysis.main:app``。

审查文档 §6.3：api_prefix 由 Settings 提供，应用工厂统一注册路由，
配置与实际行为一致。
"""

from __future__ import annotations

from stockwise_analysis.api.routes import create_api_app
from stockwise_analysis.config import Settings
from stockwise_analysis.runtime.application import create_application

_settings = Settings.from_environment()
_application = create_application(_settings)
app = create_api_app(_application, api_prefix=_settings.api_prefix)

__all__ = ["app"]
