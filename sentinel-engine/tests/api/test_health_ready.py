"""Liveness / Readiness 分离测试（P0）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bdlh_runtime.api.routes import create_api_app
from bdlh_runtime.config import Settings
from bdlh_runtime.infra.application import create_application
from bdlh_runtime.infra.dependency_probes import ProbeResult
from bdlh_runtime.infra.errors import ConfigurationError
from tests.helpers_application import build_isolated_application
from tests.helpers_registry import seeded_snapshot


def _app(**settings_kwargs):
    settings_kwargs.setdefault("auth_required", False)
    settings = Settings(**settings_kwargs)
    return create_api_app(
        build_isolated_application(settings=settings),
        api_prefix="/api/v1",
    )


def _full_prod_settings(**overrides) -> Settings:
    base = dict(
        environment="production",
        auth_required=True,
        java_api_base_url="http://java.example",
        java_data_internal_token="token",
        llm_api_key="llm-key",
        fastpath_embedder_base_url="http://embed.example/v1",
        memory_mode="remote",
        memory_service_base_url="http://memory.example",
        memory_service_internal_token="mem-token",
        jwt_secret="x" * 32,
    )
    base.update(overrides)
    return Settings(**base)


def test_health_is_liveness_only(monkeypatch):
    monkeypatch.setattr(
        "bdlh_runtime.infra.readiness.probe_java_data_plane",
        lambda base_url, timeout_seconds=2.0: ProbeResult("java_data_plane", False, "down"),
    )
    client = TestClient(_app())
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "UP"
    assert client.get("/health").status_code == 200


def test_ready_fails_when_deep_research_enabled_without_bailian(monkeypatch):
    monkeypatch.setattr(
        "bdlh_runtime.infra.readiness.probe_java_data_plane",
        lambda base_url, timeout_seconds=2.0: ProbeResult("java_data_plane", True, "HTTP 200"),
    )
    monkeypatch.setattr(
        "bdlh_runtime.infra.readiness.probe_memory_service",
        lambda base_url, timeout_seconds=2.0: ProbeResult("memory_service", True, "HTTP 200"),
    )
    client = TestClient(
        _app(
            java_api_base_url="http://127.0.0.1:8081",
            java_data_internal_token="token",
            jwt_secret="test-jwt-secret-with-at-least-thirty-two-bytes",
            auth_required=True,
            memory_mode="remote",
            memory_service_base_url="http://memory.example",
            memory_service_internal_token="mem-token",
            deep_research_enabled=True,
            bailian_web_search_api_key=None,
        )
    )
    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "NOT_READY"
    assert any(item["name"] == "deep_research.bailian" and not item["ok"] for item in body["checks"])


def test_ready_ok_when_java_probe_passes(monkeypatch):
    monkeypatch.setattr(
        "bdlh_runtime.infra.readiness.probe_java_data_plane",
        lambda base_url, timeout_seconds=2.0: ProbeResult("java_data_plane", True, "HTTP 200"),
    )
    monkeypatch.setattr(
        "bdlh_runtime.infra.readiness.probe_memory_service",
        lambda base_url, timeout_seconds=2.0: ProbeResult("memory_service", True, "HTTP 200"),
    )
    client = TestClient(
        _app(
            java_api_base_url="http://java.example",
            java_data_internal_token="token",
            auth_required=False,
            memory_mode="remote",
            memory_service_base_url="http://memory.example",
            memory_service_internal_token="mem-token",
        )
    )
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "READY"
    assert any(item["name"] == "java_data_plane" and item["ok"] for item in body["checks"])
    assert client.get("/ready").status_code == 200


def test_ready_503_when_java_unreachable(monkeypatch):
    monkeypatch.setattr(
        "bdlh_runtime.infra.readiness.probe_java_data_plane",
        lambda base_url, timeout_seconds=2.0: ProbeResult("java_data_plane", False, "down"),
    )
    monkeypatch.setattr(
        "bdlh_runtime.infra.readiness.probe_memory_service",
        lambda base_url, timeout_seconds=2.0: ProbeResult("memory_service", True, "HTTP 200"),
    )
    client = TestClient(
        _app(
            java_api_base_url="http://java.example",
            java_data_internal_token="token",
            memory_mode="remote",
            memory_service_base_url="http://memory.example",
            memory_service_internal_token="mem-token",
        )
    )
    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "NOT_READY"


def test_ready_503_when_remote_memory_down(monkeypatch):
    monkeypatch.setattr(
        "bdlh_runtime.infra.readiness.probe_java_data_plane",
        lambda base_url, timeout_seconds=2.0: ProbeResult("java_data_plane", True, "HTTP 200"),
    )
    monkeypatch.setattr(
        "bdlh_runtime.infra.readiness.probe_memory_service",
        lambda base_url, timeout_seconds=2.0: ProbeResult("memory_service", False, "down"),
    )
    client = TestClient(
        _app(
            java_api_base_url="http://java.example",
            java_data_internal_token="token",
            memory_mode="remote",
            memory_service_base_url="http://memory.example",
            memory_service_internal_token="mem-token",
        )
    )
    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert any(item["name"] == "memory_service" and not item["ok"] for item in response.json()["checks"])


def test_production_startup_fails_when_java_actuator_down(monkeypatch):
    monkeypatch.setattr(
        "bdlh_runtime.infra.dependency_probes.probe_java_data_plane",
        lambda base_url, timeout_seconds=2.0: ProbeResult("java_data_plane", False, "down"),
    )
    with pytest.raises(ConfigurationError, match="Java Data Plane 不可达"):
        create_application(
            _full_prod_settings(),
            registry_snapshot=seeded_snapshot(),
        )


def test_production_requires_internal_token():
    with pytest.raises(ConfigurationError, match="JAVA_DATA_INTERNAL_TOKEN"):
        create_application(
            _full_prod_settings(java_data_internal_token=None),
            registry_snapshot=seeded_snapshot(),
        )


def test_development_startup_fails_when_java_actuator_down(monkeypatch):
    """G3：development 与 production 一样，Java 不可达则拒绝启动。"""
    monkeypatch.setattr(
        "bdlh_runtime.infra.dependency_probes.probe_java_data_plane",
        lambda base_url, timeout_seconds=2.0: ProbeResult("java_data_plane", False, "down"),
    )
    with pytest.raises(ConfigurationError, match="Java Data Plane 不可达"):
        create_application(
            _full_prod_settings(environment="development", auth_required=False, jwt_secret=None),
            registry_snapshot=seeded_snapshot(),
        )


def test_ready_503_when_development_missing_internal_token(monkeypatch):
    monkeypatch.setattr(
        "bdlh_runtime.infra.readiness.probe_java_data_plane",
        lambda base_url, timeout_seconds=2.0: ProbeResult("java_data_plane", True, "HTTP 200"),
    )
    settings = Settings(
        environment="development",
        java_api_base_url="http://java.example",
        auth_required=False,
        memory_mode="remote",
        memory_service_base_url="http://memory.example",
        memory_service_internal_token="mem-token",
    )
    app = build_isolated_application(settings=Settings(auth_required=False))
    from types import SimpleNamespace

    from bdlh_runtime.infra.readiness import evaluate_readiness

    report = evaluate_readiness(
        SimpleNamespace(
            settings=settings,
            capability_registry=app.capability_registry,
            cognitive_application=app.cognitive_application,
        )
    )
    assert report.ready is False
    assert any(item.name == "config.java_data_internal_token" and not item.ok for item in report.checks)
