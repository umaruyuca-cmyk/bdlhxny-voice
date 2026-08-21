import pytest
from tests.helpers_registry import seeded_snapshot

from bdlh_runtime.config import Settings
from bdlh_runtime.runtime.application import create_application
from bdlh_runtime.runtime.dependency_probes import ProbeResult
from bdlh_runtime.runtime.errors import ConfigurationError


def test_production_requires_java_data_plane():
    """生产配置不能退化到 Python 本地持久化。"""

    with pytest.raises(ConfigurationError, match="JAVA_API_BASE_URL"):
        create_application(Settings(environment="production"), registry_snapshot=seeded_snapshot())


def test_development_requires_java_data_plane() -> None:
    with pytest.raises(ConfigurationError, match="JAVA_API_BASE_URL"):
        create_application(Settings(environment="development"), registry_snapshot=seeded_snapshot())


def test_test_environment_assembles_with_injected_fakes():
    """仅 environment=test 允许无 Java 装配；缺 LLM 时用确定性降级组件。

    G3：产品路径（development/production）不得靠 mock 假成功启动。
    """
    app = create_application(Settings(environment="test"), registry_snapshot=seeded_snapshot())
    assert app.cognitive_application is not None
    assert not hasattr(app, "graph")
    assert not hasattr(app, "traffic_router")
    assert not hasattr(app, "rollout_metrics")
    assert app.llm is None
    assert app.direct_response_model is not None
    assert not hasattr(app, "query_agent")
    assert not hasattr(app, "summary_model")
    assert app.gateway_adapter is not None
    assert app.domain_registry.get("finance") is app.finance_runtime
    assert app.finance_runtime is not None
    assert app.analysis_capability is not None
    assert not hasattr(app.finance_runtime, "checkpointer")


def test_product_domains_only_finance():
    app = create_application(Settings(environment="test"), registry_snapshot=seeded_snapshot())

    assert app.domain_registry.list_domains() == ["finance"]
    assert app.domain_registry.descriptor("finance") is not None
    assert app.cognitive_application._enabled_domains == frozenset({"finance"})


def test_test_environment_keeps_in_memory_m0_stores():
    from bdlh_runtime.runtime.history import InMemoryAnalysisHistoryStore
    from bdlh_runtime.runtime.run_registry import InMemoryRunRegistry

    app = create_application(Settings(environment="test"), registry_snapshot=seeded_snapshot())
    assert isinstance(app.run_registry, InMemoryRunRegistry)
    assert isinstance(app.history_store, InMemoryAnalysisHistoryStore)


def test_development_requires_internal_token():
    with pytest.raises(ConfigurationError, match="JAVA_DATA_INTERNAL_TOKEN"):
        create_application(
            Settings(environment="development", java_api_base_url="http://java.example"),
            registry_snapshot=seeded_snapshot(),
        )


def test_java_api_base_url_selects_remote_stores(monkeypatch):
    sentinel_history = object()
    sentinel_registry = object()
    sentinel_chat = object()
    sentinel_tasks = object()
    sentinel_outbox = object()

    def _fake_remote(*, base_url, internal_token):
        assert base_url == "http://java.example"
        assert internal_token == "token"
        return sentinel_history, sentinel_registry, sentinel_chat

    def _fake_remote_tasks(*, base_url, internal_token):
        assert base_url == "http://java.example"
        return sentinel_tasks, sentinel_outbox

    monkeypatch.setattr(
        "bdlh_runtime.runtime.dependency_probes.probe_java_data_plane",
        lambda base_url, timeout_seconds=2.0: ProbeResult("java_data_plane", True, "ok"),
    )
    monkeypatch.setattr(
        "bdlh_runtime.runtime.remote_runtime_data.create_remote_runtime_stores",
        _fake_remote,
    )
    monkeypatch.setattr(
        "bdlh_runtime.runtime.remote_tasks.create_remote_task_stores",
        _fake_remote_tasks,
    )

    app = create_application(
        Settings(
            environment="development",
            java_api_base_url="http://java.example",
            java_data_internal_token="token",
            auth_required=False,
        ),
        registry_snapshot=seeded_snapshot(),
    )
    assert app.history_store is sentinel_history
    assert app.run_registry is sentinel_registry
    assert app.chat_session_store is sentinel_chat
    assert app.task_store is sentinel_tasks
    assert app.notification_outbox is sentinel_outbox
