from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_LLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_LLM_MODEL = "glm-4.7"


def _first_env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    internal_token: str | None = None
    postgres_dsn: str | None = None
    rocketmq_enabled: bool = False
    rocketmq_endpoints: str = "rmq-broker:8081"
    mem0_llm_model: str = DEFAULT_LLM_MODEL
    mem0_llm_api_key: str | None = None
    mem0_llm_base_url: str = DEFAULT_LLM_BASE_URL
    mem0_embedder_model: str = "Qwen3-Embedding"
    mem0_embedder_api_key: str | None = None
    mem0_embedder_base_url: str | None = None
    mem0_config_json: str | None = None

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            environment=os.getenv("BDLH_RUNTIME_ENV", "development"),
            internal_token=os.getenv("MEMORY_SERVICE_INTERNAL_TOKEN"),
            postgres_dsn=os.getenv("MEMORY_POSTGRES_DSN"),
            rocketmq_enabled=os.getenv("MEMORY_ROCKETMQ_ENABLED", "false").lower() in {"1", "true", "yes"},
            rocketmq_endpoints=os.getenv("ROCKETMQ_ENDPOINTS", "rmq-broker:8081"),
            mem0_llm_model=_first_env("LLM_MODEL", "MEM0_LLM_MODEL", default=DEFAULT_LLM_MODEL) or DEFAULT_LLM_MODEL,
            mem0_llm_api_key=_first_env("LLM_API_KEY", "DEEPSEEK_API_KEY"),
            mem0_llm_base_url=_first_env("LLM_BASE_URL", "DEEPSEEK_BASE_URL", default=DEFAULT_LLM_BASE_URL)
            or DEFAULT_LLM_BASE_URL,
            mem0_embedder_model=os.getenv("MEM0_EMBEDDER_MODEL", "Qwen3-Embedding"),
            mem0_embedder_api_key=os.getenv("QWEN3_API_KEY"),
            mem0_embedder_base_url=os.getenv("QWEN3_BASE_URL"),
            mem0_config_json=os.getenv("MEM0_CONFIG_JSON"),
        )
