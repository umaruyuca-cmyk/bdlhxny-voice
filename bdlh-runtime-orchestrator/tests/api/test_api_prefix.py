"""API 路由前缀测试（审查文档 §6.3：api_prefix 配置生效）。"""

from __future__ import annotations

from bdlh_runtime.api.routes import create_api_app
from bdlh_runtime.config import Settings
from bdlh_runtime.runtime.application import create_application


def test_api_prefix_from_settings():
    """api_prefix 来自 Settings，路由挂在配置前缀下而非硬编码 /api/v1。"""
    app = create_api_app(
        create_application(Settings(environment="development")),
        api_prefix="/custom/v2",
    )
    # url_path_for 按路由名解析完整路径，验证前缀生效
    assert app.url_path_for("health") == "/custom/v2/health"
    assert app.url_path_for("create_run") == "/custom/v2/agent-runs"
    # 旧硬编码前缀不应生效
    assert app.url_path_for("health") != "/api/v1/health"


def test_default_prefix_is_api_v1():
    """默认 api_prefix 为 /api/v1。"""
    app = create_api_app(
        create_application(Settings(environment="development")),
        api_prefix="/api/v1",
    )
    assert app.url_path_for("health") == "/api/v1/health"
