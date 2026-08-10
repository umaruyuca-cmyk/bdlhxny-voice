"""应用配置入口。

配置只描述运行边界，不在 Graph 节点内读取环境变量。这样测试、命令行和
未来的容器部署可以注入不同配置，而不会改变业务流程代码。

分组说明：
- 基础运行：environment / checkpointer / API 前缀，控制服务启停行为。
- MCP 数据源：两个金融 MCP 的传输方式与端点，传输协议不同必须分别配置。
- 记忆层：Mem0 内部使用的 LLM 与 Embedding，显式指定避免走默认 OpenAI。
- 模型凭证：DeepSeek 与 Qwen3 的接入参数，供记忆层和后续 Agent 使用。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class McpSourceConfig:
    """单个 MCP 服务的连接配置。

    transport 必须显式区分：cn-financial 用 sse，akshare-one 用 streamable_http。
    两者客户端解包方式相同（2 元组），但底层握手协议不同，不能假设统一接口。
    """

    transport: str           # "sse" 或 "streamable_http"
    endpoint: str            # 完整 URL，如 http://host:port/sse
    timeout_seconds: float = 20.0
    token: str | None = None  # 部分部署需要鉴权 token


@dataclass(frozen=True)
class Mem0Config:
    """Mem0 记忆层配置。

    内部 LLM 和 Embedding 必须显式指定为本项目使用的模型，不得走 Mem0 默认
    的 OpenAI——否则会引入未声明的外部依赖和成本。Mem0 不可用时由
    NoOpMemoryStore 降级，主流程不受影响（见 memory/noop.py）。
    """

    llm_model: str = "deepseek-chat"          # Mem0 内部抽取/去重用的 LLM
    llm_api_key: str | None = None            # DeepSeek API Key
    llm_base_url: str = "https://api.deepseek.com"
    embedder_model: str = "Qwen3-Embedding"   # 向量化模型
    embedder_api_key: str | None = None       # Qwen3 服务 Key
    embedder_base_url: str | None = None      # Qwen3 服务地址


@dataclass(frozen=True)
class Settings:
    """StockWise Python 服务的完整运行配置。"""

    # ── 基础运行 ──
    environment: str = "development"
    checkpointer_backend: str = "memory"
    api_prefix: str = "/api/v1"
    max_event_wait_seconds: float = 30.0

    # ── MCP 数据源（两个服务传输协议不同，必须分别配置）──
    mcp_akshare_one: McpSourceConfig = field(
        default_factory=lambda: McpSourceConfig(
            transport="streamable_http",
            endpoint=os.getenv("AKSHARE_ONE_MCP_ENDPOINT", "http://118.25.178.86:8083/mcp"),
        )
    )
    mcp_cn_financial: McpSourceConfig = field(
        default_factory=lambda: McpSourceConfig(
            transport="sse",
            endpoint=os.getenv("CN_FINANCIAL_MCP_ENDPOINT", "http://118.25.178.86:8000/sse"),
        )
    )

    # ── 记忆层 ──
    mem0: Mem0Config = field(default_factory=Mem0Config)

    # ── 模型凭证（供记忆层和后续 Agent 使用）──
    deepseek_api_key: str | None = None
    qwen3_base_url: str | None = None

    @classmethod
    def from_environment(cls) -> "Settings":
        """从环境变量读取配置；生产环境应由部署系统统一注入。

        所有可变参数都走环境变量，dataclass 本身 frozen 不可变，
        保证一次请求生命周期内配置稳定。
        """

        return cls(
            environment=os.getenv("STOCKWISE_ENV", "development"),
            checkpointer_backend=os.getenv("STOCKWISE_CHECKPOINTER_BACKEND", "memory"),
            api_prefix=os.getenv("STOCKWISE_API_PREFIX", "/api/v1"),
            max_event_wait_seconds=float(os.getenv("STOCKWISE_MAX_EVENT_WAIT_SECONDS", "30")),
            mcp_akshare_one=McpSourceConfig(
                transport=os.getenv("AKSHARE_ONE_MCP_TRANSPORT", "streamable_http"),
                endpoint=os.getenv("AKSHARE_ONE_MCP_ENDPOINT", "http://118.25.178.86:8083/mcp"),
                timeout_seconds=float(os.getenv("AKSHARE_ONE_MCP_TIMEOUT", "20")),
                token=os.getenv("AKSHARE_ONE_MCP_TOKEN"),
            ),
            mcp_cn_financial=McpSourceConfig(
                transport=os.getenv("CN_FINANCIAL_MCP_TRANSPORT", "sse"),
                endpoint=os.getenv("CN_FINANCIAL_MCP_ENDPOINT", "http://118.25.178.86:8000/sse"),
                timeout_seconds=float(os.getenv("CN_FINANCIAL_MCP_TIMEOUT", "20")),
                token=os.getenv("CN_FINANCIAL_MCP_TOKEN"),
            ),
            mem0=Mem0Config(
                llm_model=os.getenv("MEM0_LLM_MODEL", "deepseek-chat"),
                llm_api_key=os.getenv("DEEPSEEK_API_KEY"),
                llm_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                embedder_model=os.getenv("MEM0_EMBEDDER_MODEL", "Qwen3-Embedding"),
                embedder_api_key=os.getenv("QWEN3_API_KEY"),
                embedder_base_url=os.getenv("QWEN3_BASE_URL"),
            ),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
            qwen3_base_url=os.getenv("QWEN3_BASE_URL"),
        )
