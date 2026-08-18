import pytest

from bdlh_runtime.config import Settings
from bdlh_runtime.runtime.application import create_application
from tests.helpers_registry import seeded_snapshot
from bdlh_runtime.runtime.errors import ConfigurationError


def test_production_requires_persistent_checkpointer():
    """生产配置不能静默退化到内存 Checkpointer。"""

    with pytest.raises(ConfigurationError):
        create_application(Settings(environment="production"), registry_snapshot=seeded_snapshot())


def test_development_assembles_with_graceful_degradation():
    """开发环境（无 API Key）应正常装配，所有组件降级为规则/NoOp 版。

    验证 Phase 1 核心原则：外部依赖不可用时不阻断启动，只是质量降级。
    """
    app = create_application(Settings(environment="development"), registry_snapshot=seeded_snapshot())
    assert app.graph is not None
    # 无 DeepSeek Key → LLM 为 None → 各 Agent 降级为规则版
    assert app.llm is None
    assert app.query_agent is not None  # 规则版 QueryAgent
    assert app.summary_model is not None  # 确定性版 SummaryModel
    assert app.gateway_adapter is not None  # Gateway 创建成功（连接探测延迟到调用时）
    assert app.domain_registry.get("finance") is app.finance_runtime
    assert app.finance_runtime is not None
    assert app.cognitive_application is not None
    assert not hasattr(app.finance_runtime, "checkpointer")


def test_m7_second_domain_is_registered_but_not_user_enabled():
    app = create_application(Settings(environment="development"), registry_snapshot=seeded_snapshot())

    assert app.domain_registry.list_domains() == ["finance", "plugin_probe"]
    descriptor = app.domain_registry.descriptor("plugin_probe")
    assert descriptor is not None and descriptor.status == "EXPERIMENTAL"
    assert app.cognitive_application._enabled_domains == frozenset({"finance"})


def test_development_keeps_in_memory_m0_stores():
    from bdlh_runtime.runtime.history import InMemoryAnalysisHistoryStore
    from bdlh_runtime.runtime.run_registry import InMemoryRunRegistry

    app = create_application(Settings(environment="development"), registry_snapshot=seeded_snapshot())
    assert isinstance(app.run_registry, InMemoryRunRegistry)
    assert isinstance(app.history_store, InMemoryAnalysisHistoryStore)
