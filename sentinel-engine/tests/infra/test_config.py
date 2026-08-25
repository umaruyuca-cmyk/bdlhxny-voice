"""演示部署档配置项单测（WO-T0-3）。

覆盖 `Settings.demo_mode` 默认值与 `BDLH_DEMO_MODE` 环境变量解析两态。
设计文档 §4.8、C-4：demo_mode 控制演示注入端点注册与前端演示标识。
"""

from __future__ import annotations

import pytest

from bdlh_runtime.config import Settings


def test_demo_mode_defaults_to_false_on_direct_construction():
    """直接构造 Settings 时 demo_mode 默认 False（生产档口径）。"""
    settings = Settings(environment="production", memory_mode="remote")
    assert settings.demo_mode is False


def test_demo_mode_can_be_explicitly_enabled():
    """显式开启 demo_mode。"""
    settings = Settings(environment="production", memory_mode="remote", demo_mode=True)
    assert settings.demo_mode is True


def test_from_environment_defaults_demo_mode_false_when_unset(monkeypatch: pytest.MonkeyPatch):
    """BDLH_DEMO_MODE 未设置时，from_environment 解析为 False。"""
    monkeypatch.delenv("BDLH_DEMO_MODE", raising=False)
    # 避免宿主环境其它变量干扰：保证 memory_mode 走默认 remote
    monkeypatch.delenv("BDLH_MEMORY_MODE", raising=False)
    settings = Settings.from_environment()
    assert settings.demo_mode is False


@pytest.mark.parametrize("raw", ["true", "True", "1", "yes", "on"])
def test_from_environment_enables_demo_mode_for_truthy_values(
    monkeypatch: pytest.MonkeyPatch, raw: str
):
    """BDLH_DEMO_MODE 取真值集合时，from_environment 解析为 True。"""
    monkeypatch.setenv("BDLH_DEMO_MODE", raw)
    monkeypatch.delenv("BDLH_MEMORY_MODE", raising=False)
    settings = Settings.from_environment()
    assert settings.demo_mode is True


@pytest.mark.parametrize("raw", ["false", "0", "no", "off", ""])
def test_from_environment_keeps_demo_mode_false_for_falsy_values(
    monkeypatch: pytest.MonkeyPatch, raw: str
):
    """BDLH_DEMO_MODE 取假值或空时，from_environment 解析为 False。"""
    monkeypatch.setenv("BDLH_DEMO_MODE", raw)
    monkeypatch.delenv("BDLH_MEMORY_MODE", raising=False)
    settings = Settings.from_environment()
    assert settings.demo_mode is False


def test_session_history_turns_defaults_to_ten():
    settings = Settings(environment="production", memory_mode="remote")
    assert settings.session_history_turns == 10


def test_from_environment_reads_session_history_turns(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BDLH_SESSION_HISTORY_TURNS", "4")
    monkeypatch.delenv("BDLH_MEMORY_MODE", raising=False)
    settings = Settings.from_environment()
    assert settings.session_history_turns == 4


def test_tool_loading_defaults_to_scoped():
    settings = Settings(environment="production", memory_mode="remote")
    assert settings.tool_loading == "scoped"


def test_from_environment_defaults_tool_loading_scoped(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("BDLH_TOOL_LOADING", raising=False)
    monkeypatch.delenv("BDLH_MEMORY_MODE", raising=False)
    settings = Settings.from_environment()
    assert settings.tool_loading == "scoped"


def test_from_environment_reads_tool_loading_search(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BDLH_TOOL_LOADING", "search")
    monkeypatch.delenv("BDLH_MEMORY_MODE", raising=False)
    settings = Settings.from_environment()
    assert settings.tool_loading == "search"


def test_from_environment_rejects_invalid_tool_loading(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BDLH_TOOL_LOADING", "all")
    monkeypatch.delenv("BDLH_MEMORY_MODE", raising=False)
    with pytest.raises(ValueError, match="BDLH_TOOL_LOADING"):
        Settings.from_environment()
