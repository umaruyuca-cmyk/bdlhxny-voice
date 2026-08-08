"""ASGI 应用入口；部署命令使用 ``stockwise_analysis.main:app``。"""

from stockwise_analysis.api.routes import app

__all__ = ["app"]
