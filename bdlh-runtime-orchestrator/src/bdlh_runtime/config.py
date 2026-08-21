"""应用配置入口。

配置只描述运行边界，不在业务编排内读取环境变量。这样测试、命令行和
未来的容器部署可以注入不同配置，而不会改变业务流程代码。

分组说明：
- 基础运行：environment / API 前缀，控制服务启停行为。
- MCP 数据源：两个金融 MCP 的传输方式与端点，传输协议不同必须分别配置。
- 记忆层：Mem0 内部使用的 LLM 与 Embedding，显式指定避免走默认 OpenAI。
- 模型凭证：LLM（默认 GLM-4.7）与 Qwen3 的接入参数，供记忆层和后续 Agent 使用。

产品配置一律按生产标准装配：无 noop/embedded-test/lexical 等产品降级分支。
隔离单测请用 ``tests/helpers_application.py``，不要在 Settings 上开测试逃生门。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from bdlh_runtime.runtime.llm import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL


def _first_env(*names: str, default: str | None = None) -> str | None:
    """按优先级读取环境变量；空字符串视为未设置。"""
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


@dataclass(frozen=True)
class McpSourceConfig:
    """单个 MCP 服务的连接配置。

    transport 必须显式区分：cn-financial 用 sse，akshare-one 用 streamable_http。
    两者客户端解包方式相同（2 元组），但底层握手协议不同，不能假设统一接口。
    """

    transport: str  # "sse" 或 "streamable_http"
    endpoint: str  # 完整 URL，如 http://host:port/sse
    timeout_seconds: float = 20.0


@dataclass(frozen=True)
class Mem0Config:
    """Mem0 记忆层配置（由独立 Memory Service 消费）。

    内部 LLM 和 Embedding 必须显式指定为本项目使用的模型，不得走 Mem0 默认
    的 OpenAI——否则会引入未声明的外部依赖和成本。产品路径只走 Remote
    Memory Service；Orchestrator 不再以 NoOp 作为配置级降级。
    """

    llm_model: str = DEFAULT_LLM_MODEL  # Mem0 内部抽取/去重用的 LLM
    llm_api_key: str | None = None  # 智谱 / OpenAI 兼容 API Key
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    embedder_model: str = "Qwen3-Embedding"  # 向量化模型
    embedder_api_key: str | None = None  # Qwen3 服务 Key
    embedder_base_url: str | None = None  # Qwen3 服务地址


@dataclass(frozen=True)
class Settings:
    """BDLH Agent Runtime Python 服务的完整运行配置。"""

    # ── 基础运行 ──
    environment: str = "production"
    api_prefix: str = "/api/v1"
    max_event_wait_seconds: float = 30.0
    auth_required: bool = True
    jwt_secret: str | None = None
    # ── M6 持续任务 Worker ──
    financial_task_worker_enabled: bool = False
    financial_task_poll_seconds: float = 10.0
    # Chat/Run/History/Task 均由 Java Data Plane 持久化。
    java_api_base_url: str | None = None
    java_data_internal_token: str | None = None
    # 产品仅允许 Remote Memory Service；noop / embedded-test 已从产品配置移除。
    memory_mode: str = "remote"
    memory_service_base_url: str | None = None
    memory_service_internal_token: str | None = None

    # ── MCP 数据源（两个服务传输协议不同，必须分别配置）──
    mcp_akshare_one: McpSourceConfig = field(
        default_factory=lambda: McpSourceConfig(
            transport="streamable_http",
            endpoint=os.getenv("AKSHARE_ONE_MCP_ENDPOINT", "http://127.0.0.1:8083/mcp"),
        )
    )
    mcp_cn_financial: McpSourceConfig = field(
        default_factory=lambda: McpSourceConfig(
            transport="sse",
            endpoint=os.getenv("CN_FINANCIAL_MCP_ENDPOINT", "http://127.0.0.1:8000/sse"),
        )
    )

    # ── 记忆层 ──
    mem0: Mem0Config = field(default_factory=Mem0Config)

    # ── bdlh-web-search-adapter（网络搜索服务，HTTP 非 MCP）──
    # 双凭证：agent_id（x-agent-id）+ token（x-search-token），见 wrapper auth.js
    web_search_base_url: str | None = None
    web_search_agent_id: str | None = None
    web_search_token: str | None = None
    web_search_timeout_seconds: float = 20.0

    # ── Deep Research（ADR-016；默认关闭，不改生产浅搜语义）──
    deep_research_enabled: bool = False
    bailian_web_search_api_key: str | None = None
    bailian_web_search_endpoint: str | None = None
    bailian_web_search_timeout_seconds: float = 20.0
    bailian_web_search_rate_limit_per_minute: int = 30

    # ── 资格 / 预算（配置层；非 Registry 八表）──
    runtime_allowed_operations: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "READ_MARKET_DATA",
                "READ_PUBLIC_RESEARCH",
                "READ_PORTFOLIO",
                "READ_PROFILE",
                "READ_FINANCIAL_GOALS",
                "RUN_ANALYSIS",
            }
        )
    )
    default_entitlement_operations: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "READ_MARKET_DATA",
                "READ_PUBLIC_RESEARCH",
                "READ_PORTFOLIO",
                "READ_PROFILE",
                "READ_FINANCIAL_GOALS",
                "RUN_ANALYSIS",
            }
        )
    )

    # ── 模型凭证（供记忆层和后续 Agent 使用）──
    llm_api_key: str | None = None
    qwen3_base_url: str | None = None

    # ── 快路径向量化：始终 Qwen 向量模型（与记忆层共用 Qwen3 服务）──
    fastpath_embedder_base_url: str | None = None
    fastpath_embedder_api_key: str | None = None
    fastpath_embedder_model: str = "qwen3-embedding:4b-q8_0"
    fastpath_embedder_timeout_seconds: float = 10.0

    @classmethod
    def from_environment(cls) -> Settings:
        """从环境变量读取配置；生产环境应由部署系统统一注入。

        所有可变参数都走环境变量，dataclass 本身 frozen 不可变，
        保证一次请求生命周期内配置稳定。
        """

        environment = os.getenv("BDLH_RUNTIME_ENV", "production")
        # G3：产品默认要求配置 JWT_SECRET（登录用户可校验）；缺 Token 按游客对话，
        # 不拦截 chat/agent-runs。登录专属能力由 authenticated_task_user 强制。
        jwt_secret = os.getenv("JWT_SECRET")
        memory_mode = os.getenv("BDLH_MEMORY_MODE", "remote").strip().lower()
        if memory_mode != "remote":
            raise ValueError(
                "BDLH_MEMORY_MODE 仅支持 remote；noop/embedded-test 已从产品配置移除"
            )
        return cls(
            environment=environment,
            api_prefix=os.getenv("BDLH_RUNTIME_API_PREFIX", "/api/v1"),
            max_event_wait_seconds=float(os.getenv("BDLH_RUNTIME_MAX_EVENT_WAIT_SECONDS", "30")),
            auth_required=os.getenv("BDLH_RUNTIME_AUTH_REQUIRED", "true").lower()
            in {"1", "true", "yes", "on"},
            jwt_secret=jwt_secret,
            financial_task_worker_enabled=os.getenv("BDLH_FINANCIAL_TASK_WORKER_ENABLED", "false").lower()
            in {"1", "true", "yes", "on"},
            financial_task_poll_seconds=float(os.getenv("BDLH_FINANCIAL_TASK_POLL_SECONDS", "10")),
            java_api_base_url=os.getenv("JAVA_API_BASE_URL"),
            java_data_internal_token=os.getenv("JAVA_DATA_INTERNAL_TOKEN"),
            memory_mode=memory_mode,
            memory_service_base_url=os.getenv("MEMORY_SERVICE_BASE_URL"),
            memory_service_internal_token=os.getenv("MEMORY_SERVICE_INTERNAL_TOKEN"),
            mcp_akshare_one=McpSourceConfig(
                transport=os.getenv("AKSHARE_ONE_MCP_TRANSPORT", "streamable_http"),
                endpoint=os.getenv("AKSHARE_ONE_MCP_ENDPOINT", "http://127.0.0.1:8083/mcp"),
                timeout_seconds=float(os.getenv("AKSHARE_ONE_MCP_TIMEOUT", "20")),
            ),
            mcp_cn_financial=McpSourceConfig(
                transport=os.getenv("CN_FINANCIAL_MCP_TRANSPORT", "sse"),
                endpoint=os.getenv("CN_FINANCIAL_MCP_ENDPOINT", "http://127.0.0.1:8000/sse"),
                timeout_seconds=float(os.getenv("CN_FINANCIAL_MCP_TIMEOUT", "20")),
            ),
            mem0=Mem0Config(
                llm_model=_first_env("LLM_MODEL", "MEM0_LLM_MODEL", default=DEFAULT_LLM_MODEL) or DEFAULT_LLM_MODEL,
                llm_api_key=_first_env("LLM_API_KEY", "DEEPSEEK_API_KEY"),
                llm_base_url=_first_env("LLM_BASE_URL", "DEEPSEEK_BASE_URL", default=DEFAULT_LLM_BASE_URL)
                or DEFAULT_LLM_BASE_URL,
                embedder_model=os.getenv("MEM0_EMBEDDER_MODEL", "Qwen3-Embedding"),
                embedder_api_key=os.getenv("QWEN3_API_KEY"),
                embedder_base_url=os.getenv("QWEN3_BASE_URL"),
            ),
            llm_api_key=_first_env("LLM_API_KEY", "DEEPSEEK_API_KEY"),
            qwen3_base_url=os.getenv("QWEN3_BASE_URL"),
            fastpath_embedder_base_url=os.getenv("FASTPATH_EMBEDDER_BASE_URL")
            or os.getenv("QWEN3_BASE_URL"),
            fastpath_embedder_api_key=os.getenv("FASTPATH_EMBEDDER_API_KEY")
            or os.getenv("QWEN3_API_KEY"),
            fastpath_embedder_model=_first_env(
                "FASTPATH_EMBEDDER_MODEL",
                "MEM0_EMBEDDER_MODEL",
                default="qwen3-embedding:4b-q8_0",
            ),
            fastpath_embedder_timeout_seconds=float(os.getenv("FASTPATH_EMBEDDER_TIMEOUT_SECONDS", "10")),
            web_search_base_url=os.getenv("WEB_SEARCH_BASE_URL"),
            web_search_agent_id=os.getenv("WEB_SEARCH_AGENT_ID"),
            web_search_token=os.getenv("WEB_SEARCH_TOKEN"),
            web_search_timeout_seconds=float(os.getenv("WEB_SEARCH_TIMEOUT", "20")),
            deep_research_enabled=os.getenv("BDLH_DEEP_RESEARCH_ENABLED", "false").lower()
            in {"1", "true", "yes", "on"},
            bailian_web_search_api_key=os.getenv("BDLH_BAILIAN_WEB_SEARCH_API_KEY") or os.getenv("DASHSCOPE_API_KEY"),
            bailian_web_search_endpoint=os.getenv("BDLH_BAILIAN_WEB_SEARCH_ENDPOINT"),
            bailian_web_search_timeout_seconds=float(os.getenv("BDLH_BAILIAN_WEB_SEARCH_TIMEOUT", "20")),
            bailian_web_search_rate_limit_per_minute=int(
                os.getenv("BDLH_BAILIAN_WEB_SEARCH_RATE_LIMIT_PER_MINUTE", "30")
            ),
            runtime_allowed_operations=_ops_from_env(
                "RUNTIME_ALLOWED_OPERATIONS",
                {
                    "READ_MARKET_DATA",
                    "READ_PUBLIC_RESEARCH",
                    "READ_PORTFOLIO",
                    "READ_PROFILE",
                    "READ_FINANCIAL_GOALS",
                    "RUN_ANALYSIS",
                },
            ),
            default_entitlement_operations=_ops_from_env(
                "DEFAULT_ENTITLEMENT_OPERATIONS",
                {
                    "READ_MARKET_DATA",
                    "READ_PUBLIC_RESEARCH",
                    "READ_PORTFOLIO",
                    "READ_PROFILE",
                    "READ_FINANCIAL_GOALS",
                    "RUN_ANALYSIS",
                },
            ),
        )


def _ops_from_env(name: str, default: set[str]) -> frozenset[str]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return frozenset(default)
    return frozenset(item.strip() for item in raw.split(",") if item.strip())
