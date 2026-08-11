"""应用装配入口。

负责把所有组件（LLM、Memory、Gateway、Agent）按配置创建并注入到 Root Graph。
装配原则：每个组件都走"有配置用真实版、无配置降级"的路径，保证应用在任何
环境（无 API Key、无 Mem0、无 MCP）都能启动并跑通流程——只是质量从 LLM 降到规则。

生产部署时替换 Checkpointer 实现即可，不需要修改 Graph 拓扑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from stockwise_analysis.config import Settings
from stockwise_analysis.runtimes.langgraph.agents.query_agent import create_query_agent
from stockwise_analysis.runtimes.langgraph.agents.research_agent import create_research_agent
from stockwise_analysis.runtimes.langgraph.agents.summary_model import create_summary_model
from stockwise_analysis.runtimes.langgraph.graphs.root_graph import build_root_graph

from .errors import ConfigurationError
from .llm import create_llm

# Java API 地址的环境变量名（与 config 一致）
_JAVA_API_BASE_URL_ENV = "JAVA_API_BASE_URL"


@dataclass
class StockWiseApplication:
    """已装配的应用实例，持有 Graph 和所有注入的组件。"""

    settings: Settings
    graph: Any  # 编译后的 LangGraph
    # 持有组件引用供调试和可观测性使用
    checkpointer: Any | None = None
    llm: Any | None = None
    memory_store: Any | None = None
    gateway_adapter: Any | None = None
    query_agent: Any | None = None
    summary_model: Any | None = None
    research_agent: Any | None = None
    llm_research_agent: Any | None = None
    analysis_capability: Any | None = None
    web_search_adapter: Any | None = None
    history_store: Any | None = None


def create_application(settings: Settings | None = None) -> StockWiseApplication:
    """从 Settings 装配完整应用。

    装配顺序：LLM → Memory → Gateway → Agents → Root Graph。
    每一步都可能降级（无 Key/无依赖），降级信息记日志但不阻断启动。
    """
    settings = settings or Settings.from_environment()

    # ── 0. Checkpointer（审查文档 §4.3：按配置创建，生产注入持久化后端）──
    # memory 后端在 production 被 create_checkpointer 拒绝（ConfigurationError）。
    from .checkpointers import create_checkpointer

    checkpointer = create_checkpointer(settings)

    # ── 1. LLM（有 DeepSeek Key 用真实，无则 None 触发各 Agent 降级）──
    llm = create_llm(
        api_key=settings.deepseek_api_key,
        base_url=settings.mem0.llm_base_url,
        model=settings.mem0.llm_model,
    )

    # ── 2. 记忆层（Mem0 后端不可用时降级 NoOp）──
    memory_store = _create_memory(settings)

    # ── 3. MCP Gateway（创建 client，云端不在线时调用会失败但启动不阻断）──
    gateway_adapter = _create_gateway(settings)

    # ── 4. Agents（按 LLM 有无自动选 LLM 版或规则版）──
    query_agent = create_query_agent(llm)
    summary_model = create_summary_model(llm)
    # Research Agent 双版本（审查文档 §4.5 执行矩阵）：
    # - research_agent：规则版（technical/fundamental 等有限自适应）；
    # - llm_research_agent：comprehensive 用 LLM 版（无 LLM 时也降级规则版）。
    research_agent = create_research_agent(llm, analysis_type="technical")
    llm_research_agent = create_research_agent(llm, analysis_type="comprehensive")

    # ── 4.5 Java 数据适配器（Phase 4：持仓/账户/风控画像）──
    # base_url 未配置时 Adapter 内部自动 mock 降级（见 java_data_adapter.py）
    import os as _os

    java_adapter = _create_java_adapter(
        _os.getenv(_JAVA_API_BASE_URL_ENV),
        production=(settings.environment == "production"),
        token=_os.getenv("JAVA_API_TOKEN"),
    )

    # ── 4.5b web-search 适配器（网络搜索，HTTP 非 MCP）──
    # base_url 未配置时 Adapter 内部自动 mock 降级（见 web_search_adapter.py）
    web_search_adapter = _create_web_search_adapter(settings)

    # ── 4.6 ContextBuilder（审查文档 §4.4：七块上下文组装）──
    # 从 ToolRegistry 组装工具清单；Memory 召回内容由 load_memory 节点写入
    # state，ContextBuilder 只做组装不做 I/O。
    context_builder = _create_context_builder()
    from stockwise_analysis.tools.analysis_capability import create_analysis_capability

    analysis_capability = create_analysis_capability()

    # ── 4.7 分析历史存储（v2.1 §9.3：审计/历史查询，与 Mem0 分离）──
    from .history import create_history_store

    history_store = create_history_store()

    # ── 5. Root Graph（注入全部组件）──
    graph = build_root_graph(
        checkpointer=checkpointer,
        memory_store=memory_store,
        query_agent=query_agent,
        summary_model=summary_model,
        gateway_adapter=gateway_adapter,
        research_agent=research_agent,
        llm_research_agent=llm_research_agent,
        java_adapter=java_adapter,
        context_builder=context_builder,
        analysis_capability=analysis_capability,
        web_search_adapter=web_search_adapter,
        history_store=history_store,
    )

    return StockWiseApplication(
        settings=settings,
        graph=graph,
        checkpointer=checkpointer,
        llm=llm,
        memory_store=memory_store,
        gateway_adapter=gateway_adapter,
        query_agent=query_agent,
        summary_model=summary_model,
        research_agent=research_agent,
        llm_research_agent=llm_research_agent,
        analysis_capability=analysis_capability,
        web_search_adapter=web_search_adapter,
        history_store=history_store,
    )


def _create_memory(settings: Settings) -> Any:
    """创建记忆存储，Mem0 不可用时降级 NoOp。"""
    from stockwise_analysis.memory.mem0.mem0_store import create_memory_store

    return create_memory_store(
        mem0_llm_model=settings.mem0.llm_model,
        mem0_llm_api_key=settings.mem0.llm_api_key,
        mem0_llm_base_url=settings.mem0.llm_base_url,
        mem0_embedder_model=settings.mem0.embedder_model,
        mem0_embedder_api_key=settings.mem0.embedder_api_key,
        mem0_embedder_base_url=settings.mem0.embedder_base_url,
    )


def _create_gateway(settings: Settings) -> Any:
    """创建 MCP Gateway Adapter。

    即使云端 MCP 不在线也允许启动（调用时才失败）。这与"降级不阻断启动"
    原则一致——Gateway 只是把 client 创建出来，连接探测发生在首次调用。
    """
    from stockwise_analysis.integrations.mcp.adapter import create_adapter_from_settings

    return create_adapter_from_settings(settings)


def _create_java_adapter(base_url: str | None, *, production: bool, token: str | None) -> Any:
    """创建 Java 数据适配器（Phase 4，审查文档 §5.3）。

    base_url 未配置时：开发环境 mock 降级（带 is_mock 标记），生产环境
    返回 UNAVAILABLE（不伪造持仓结论）。
    """
    from stockwise_analysis.tools.java_data_adapter import create_java_adapter

    return create_java_adapter(base_url=base_url, production=production, token=token)


def _create_web_search_adapter(settings: Settings) -> Any:
    """创建 web-search 适配器（架构文档 §13.4）。

    base_url 未配置时：开发环境 mock 降级（带 is_mock 标记），生产环境
    返回 UNAVAILABLE（不伪造搜索结果）。
    """
    from stockwise_analysis.tools.web_search_adapter import create_web_search_adapter

    return create_web_search_adapter(
        base_url=settings.web_search_base_url,
        timeout_seconds=settings.web_search_timeout_seconds,
        production=(settings.environment == "production"),
        agent_id=settings.web_search_agent_id,
        token=settings.web_search_token,
    )


def _create_context_builder() -> Any:
    """创建 ContextBuilder（审查文档 §4.4）。

    工具清单从 ToolRegistry 组装（确定性）；ContextBuilder 本身不做 I/O，
    Memory 召回内容由 load_memory 节点写入 state 后传入。
    """
    from stockwise_analysis.runtimes.langgraph.context import ContextBuilder
    from stockwise_analysis.tools.registry import ToolRegistry

    registry = ToolRegistry()
    # 注册分析能力工具（供工具清单块使用）
    from stockwise_analysis.tools.analysis_tool import register_analysis_tools

    register_analysis_tools(registry)
    tool_manifest = [
        {"name": t.name, "description": t.description, "read_only": t.read_only}
        for t in registry.list()
    ]
    return ContextBuilder(tool_manifest=tool_manifest)
