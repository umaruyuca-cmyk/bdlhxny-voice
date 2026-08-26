"""LLM 配置接线：env 是唯一真源，model 是唯一请求级可配项。"""

from __future__ import annotations

from typing import Any

import pytest

from bdlh_runtime.evaluation import context_eval
from bdlh_runtime.run_api import ContextBatchRequest


def _capture_create_llm(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_create_llm(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(context_eval, "create_llm", fake_create_llm)
    return captured


def test_build_llm_reads_env_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.internal/v1")
    captured = _capture_create_llm(monkeypatch)

    llm = context_eval.build_llm_from_env("Qwen/Qwen3.6-35B-A3B")

    assert llm is not None
    assert captured["base_url"] == "https://gateway.example.internal/v1"
    assert captured["model"] == "Qwen/Qwen3.6-35B-A3B"
    assert captured["api_key"] == "test-key"


def test_build_llm_requires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """env 是唯一真源:LLM_BASE_URL 缺失必须立即报错,不得回退内置端点。"""

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="LLM_BASE_URL 未设置"):
        context_eval.build_llm_from_env("any-model")


def test_build_llm_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="LLM_API_KEY 未设置"):
        context_eval.build_llm_from_env("any-model")


def test_request_model_defaults_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "glm-4.7")
    assert ContextBatchRequest().model == "glm-4.7"

    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert ContextBatchRequest().model == "Qwen/Qwen3.6-35B-A3B"
