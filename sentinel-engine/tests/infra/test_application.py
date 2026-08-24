import pytest
from tests.helpers_application import build_isolated_application
from tests.helpers_encoder import LexicalEncoder
from tests.helpers_registry import seeded_snapshot

from bdlh_runtime.cognitive.semantic_router.encoder import QwenEmbeddingEncoder
from bdlh_runtime.cognitive.semantic_router.fastpath_data import MODEL_FASTPATH_THRESHOLDS
from bdlh_runtime.config import Settings
from bdlh_runtime.infra.application import _fastpath_encoder, _fastpath_thresholds, create_application
from bdlh_runtime.infra.dependency_probes import ProbeResult
from bdlh_runtime.infra.errors import ConfigurationError


def _full_prod_settings(**overrides) -> Settings:
    base = dict(
        environment="production",
        auth_required=False,
        java_api_base_url="http://java.example",
        java_data_internal_token="token",
        llm_api_key="llm-key",
        fastpath_embedder_base_url="http://embed.example/v1",
        memory_mode="remote",
        memory_service_base_url="http://memory.example",
        memory_service_internal_token="mem-token",
    )
    base.update(overrides)
    return Settings(**base)


def _patch_remote_assembly(monkeypatch) -> None:
    monkeypatch.setattr(
        "bdlh_runtime.infra.dependency_probes.probe_java_data_plane",
        lambda base_url, timeout_seconds=2.0: ProbeResult("java_data_plane", True, "ok"),
    )
    monkeypatch.setattr(
        QwenEmbeddingEncoder,
        "encode",
        lambda self, texts: [[float(len(t) or 1), 1.0] for t in texts],
    )


def test_production_requires_java_data_plane():
    """生产配置不能退化到 Python 本地持久化。"""

    with pytest.raises(ConfigurationError, match="JAVA_API_BASE_URL"):
        create_application(
            Settings(
                environment="production",
                auth_required=False,
                llm_api_key="k",
                fastpath_embedder_base_url="http://embed",
                memory_service_base_url="http://m",
                memory_service_internal_token="t",
            ),
            registry_snapshot=seeded_snapshot(),
        )


def test_development_requires_java_data_plane() -> None:
    with pytest.raises(ConfigurationError, match="JAVA_API_BASE_URL"):
        create_application(
            Settings(
                environment="development",
                auth_required=False,
                llm_api_key="k",
                fastpath_embedder_base_url="http://embed",
                memory_service_base_url="http://m",
                memory_service_internal_token="t",
            ),
            registry_snapshot=seeded_snapshot(),
        )


def test_isolated_helper_assembles_without_create_application_gates():
    """隔离 helper 可装配完整 Cognitive；产品 create_application 不再接受 test 捷径。"""
    app = build_isolated_application()
    assert app.cognitive_application is not None
    assert not hasattr(app, "graph")
    assert app.llm is None
    assert app.direct_response_model is not None
    assert app.gateway_adapter is not None
    assert app.domain_registry.get("finance") is app.finance_runtime
    assert app.finance_runtime is not None
    assert app.analysis_capability is not None


def test_product_domains_follow_registry_snapshot():
    app = build_isolated_application()
    assert app.domain_registry.list_domains() == ["finance", "weather"]
    assert app.domain_registry.descriptor("finance") is not None
    assert app.domain_registry.descriptor("weather") is not None
    assert app.cognitive_application._enabled_domains == frozenset({"finance", "weather"})


def test_isolated_helper_keeps_in_memory_stores():
    from bdlh_runtime.infra.history import InMemoryAnalysisHistoryStore
    from bdlh_runtime.infra.run_registry import InMemoryRunRegistry

    app = build_isolated_application()
    assert isinstance(app.run_registry, InMemoryRunRegistry)
    assert isinstance(app.history_store, InMemoryAnalysisHistoryStore)


def test_development_requires_internal_token():
    with pytest.raises(ConfigurationError, match="JAVA_DATA_INTERNAL_TOKEN"):
        create_application(
            Settings(
                environment="development",
                auth_required=False,
                java_api_base_url="http://java.example",
                llm_api_key="k",
                fastpath_embedder_base_url="http://embed",
                memory_service_base_url="http://m",
                memory_service_internal_token="t",
            ),
            registry_snapshot=seeded_snapshot(),
        )


def test_create_application_requires_llm_and_memory_and_qwen():
    with pytest.raises(ConfigurationError, match="LLM_API_KEY"):
        create_application(
            _full_prod_settings(llm_api_key=None),
            registry_snapshot=seeded_snapshot(),
        )
    with pytest.raises(ConfigurationError, match="QWEN3_BASE_URL|FASTPATH_EMBEDDER"):
        create_application(
            _full_prod_settings(fastpath_embedder_base_url=None),
            registry_snapshot=seeded_snapshot(),
        )
    with pytest.raises(ConfigurationError, match="MEMORY_SERVICE_BASE_URL"):
        create_application(
            _full_prod_settings(memory_service_base_url=None),
            registry_snapshot=seeded_snapshot(),
        )
    with pytest.raises(ConfigurationError, match="MEMORY_SERVICE_INTERNAL_TOKEN"):
        create_application(
            _full_prod_settings(memory_service_internal_token=None),
            registry_snapshot=seeded_snapshot(),
        )
    with pytest.raises(ConfigurationError, match="仅支持 remote"):
        create_application(
            _full_prod_settings(memory_mode="noop"),
            registry_snapshot=seeded_snapshot(),
        )


def test_java_api_base_url_selects_remote_stores(monkeypatch):
    sentinel_history = object()
    sentinel_registry = object()
    sentinel_chat = object()
    sentinel_tasks = object()
    sentinel_outbox = object()
    sentinel_run_state = object()

    def _fake_remote(*, base_url, internal_token):
        assert base_url == "http://java.example"
        assert internal_token == "token"
        return sentinel_history, sentinel_registry, sentinel_chat

    def _fake_remote_tasks(*, base_url, internal_token):
        assert base_url == "http://java.example"
        return sentinel_tasks, sentinel_outbox

    def _fake_run_state(*, base_url, internal_token):
        return sentinel_run_state

    _patch_remote_assembly(monkeypatch)
    monkeypatch.setattr(
        "bdlh_runtime.infra.remote_runtime_data.create_remote_runtime_stores",
        _fake_remote,
    )
    monkeypatch.setattr(
        "bdlh_runtime.infra.remote_tasks.create_remote_task_stores",
        _fake_remote_tasks,
    )
    monkeypatch.setattr(
        "bdlh_runtime.infra.remote_run_state.create_remote_run_state_store",
        _fake_run_state,
    )

    app = create_application(
        _full_prod_settings(environment="development", auth_required=False),
        registry_snapshot=seeded_snapshot(),
    )
    assert app.history_store is sentinel_history
    assert app.run_registry is sentinel_registry
    assert app.chat_session_store is sentinel_chat
    assert app.task_store is sentinel_tasks
    assert app.notification_outbox is sentinel_outbox
    assert app.run_state_reader is sentinel_run_state
    assert isinstance(_fastpath_encoder(_full_prod_settings()), QwenEmbeddingEncoder)
    assert _fastpath_thresholds(_full_prod_settings()) == MODEL_FASTPATH_THRESHOLDS
    assert not isinstance(_fastpath_encoder(_full_prod_settings()), LexicalEncoder)
