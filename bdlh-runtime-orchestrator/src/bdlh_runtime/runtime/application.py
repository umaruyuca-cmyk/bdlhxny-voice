"""应用装配入口。

负责把所有组件（LLM、Memory、Gateway、Agent）按配置创建并注入到 Root Graph，
同时装配独立、非默认入口的 M1 Finance Runtime。
装配原则：每个组件都走"有配置用真实版、无配置降级"的路径，保证应用在任何
环境（无 API Key、无 Mem0、无 MCP）都能启动并跑通流程——只是质量从 LLM 降到规则。

Root Graph 的生产部署需替换 Checkpointer；M1 Finance Runtime 本身不接入
Checkpointer，持久化与发布门禁由 M0 单独完成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bdlh_runtime.config import Settings
from bdlh_runtime.runtimes.langgraph.agents.query_agent import create_query_agent
from bdlh_runtime.runtimes.langgraph.agents.direct_response_model import create_direct_response_model
from bdlh_runtime.runtimes.langgraph.agents.research_agent import create_research_agent
from bdlh_runtime.runtimes.langgraph.agents.summary_model import create_summary_model
from bdlh_runtime.runtimes.langgraph.graphs.root_graph import build_root_graph

from .errors import ConfigurationError
from .llm import create_llm

# Java API 地址的环境变量名（与 config 一致）
_JAVA_API_BASE_URL_ENV = "JAVA_API_BASE_URL"


@dataclass
class AgentRuntimeApplication:
    """已装配的应用实例，持有 Graph 和所有注入的组件。"""

    settings: Settings
    graph: Any  # 编译后的 LangGraph
    # 持有组件引用供调试和可观测性使用
    checkpointer: Any | None = None
    llm: Any | None = None
    memory_store: Any | None = None
    gateway_adapter: Any | None = None
    query_agent: Any | None = None
    direct_response_model: Any | None = None
    summary_model: Any | None = None
    research_agent: Any | None = None
    llm_research_agent: Any | None = None
    analysis_capability: Any | None = None
    web_search_adapter: Any | None = None
    history_store: Any | None = None
    run_registry: Any | None = None
    chat_session_store: Any | None = None
    capability_registry: Any | None = None
    domain_registry: Any | None = None
    finance_runtime: Any | None = None
    cognitive_application: Any | None = None
    traffic_router: Any | None = None
    rollout_metrics: Any | None = None
    task_store: Any | None = None
    notification_outbox: Any | None = None
    task_scheduler: Any | None = None
    notification_outbox_worker: Any | None = None


def create_application(
    settings: Settings | None = None,
    *,
    checkpointer_override: Any | None = None,
) -> AgentRuntimeApplication:
    """从 Settings 装配完整应用。

    装配顺序：LLM → Memory → Gateway → Agents → Root Graph。
    每一步都可能降级（无 Key/无依赖），降级信息记日志但不阻断启动。
    """
    settings = settings or Settings.from_environment()
    if settings.auth_required and not settings.jwt_secret:
        raise ConfigurationError("启用用户隔离时必须配置 JWT_SECRET")
    if settings.financial_task_worker_enabled and settings.financial_task_poll_seconds <= 0:
        raise ConfigurationError("M6 Worker 轮询间隔必须大于 0 秒")

    # ── 0. Checkpointer（审查文档 §4.3：按配置创建，生产注入持久化后端）──
    # memory 后端在 production 被 create_checkpointer 拒绝（ConfigurationError）。
    from .checkpointers import create_checkpointer

    checkpointer = (
        checkpointer_override
        if checkpointer_override is not None
        else create_checkpointer(settings)
    )

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
    direct_response_model = create_direct_response_model(llm)
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
        token=_os.getenv("JAVA_DATA_INTERNAL_TOKEN") or _os.getenv("JAVA_API_TOKEN"),
    )

    # ── 4.5b web-search 适配器（网络搜索，HTTP 非 MCP）──
    # base_url 未配置时 Adapter 内部自动 mock 降级（见 web_search_adapter.py）
    web_search_adapter = _create_web_search_adapter(settings)

    # ── 4.6 统一能力目录 + ContextBuilder（审查文档 §4.4）──
    from bdlh_runtime.tools.capabilities import build_default_capability_registry

    capability_registry = build_default_capability_registry()
    # 从 CapabilityRegistry 组装能力清单；Memory 召回内容由 load_memory 节点写入
    # state，ContextBuilder 只做组装不做 I/O。
    context_builder = _create_context_builder(capability_registry, memory_store=memory_store)
    from bdlh_runtime.tools.analysis_capability import create_analysis_capability

    analysis_capability = create_analysis_capability()

    # ── 4.6b M1 Finance Runtime（独立装配，不接默认 Root Graph 流量）──
    from bdlh_runtime.domains.finance.runtime import create_finance_runtime
    from bdlh_runtime.domains.registry import DomainRegistry

    finance_runtime = create_finance_runtime(
        capability_registry=capability_registry,
        gateway_adapter=gateway_adapter,
        web_search_adapter=web_search_adapter,
        analysis_capability=analysis_capability,
        java_adapter=java_adapter,
    )
    domain_registry = DomainRegistry()
    domain_registry.register("finance", finance_runtime)

    # ── 4.6c Domain Descriptor + SkillManifest 注册与启动校验（ADR-010 §3.1.2/§6）──
    # 注册 finance 域的 descriptor（声明现状），并在启动时对 Capability Registry
    # 逐项校验——不一致即 fail-fast，绝不留到运行时静默跳过。
    from bdlh_runtime.domains.finance.manifests import FINANCE_DESCRIPTOR
    from bdlh_runtime.runtime.manifest_validation import (
        validate_descriptor_against_registry,
    )

    domain_registry.register_descriptor("finance", FINANCE_DESCRIPTOR)
    validate_descriptor_against_registry(FINANCE_DESCRIPTOR, capability_registry)

    # ── 4.6c.1 M7 第二 Domain 插件契约探针（实验性、非用户入口）──
    # 仅注册 Runtime + Descriptor，并复用同一 Capability Registry 启动校验。
    # Cognitive 的 enabled_domains 仍只有 finance，因此探针不会成为产品能力。
    from bdlh_runtime.domains.plugin_probe import (
        PLUGIN_PROBE_DESCRIPTOR,
        PluginProbeRuntime,
        register_plugin_probe_capability,
    )

    # 注册发生在 ContextBuilder 已从 Registry 生成用户工具清单之后，确保实验探针
    # 不暴露到旧路径/聊天模型上下文，同时 Runtime 与校验器仍持有同一 Registry。
    register_plugin_probe_capability(capability_registry)
    domain_registry.register(
        "plugin_probe",
        PluginProbeRuntime(capability_registry),
    )
    domain_registry.register_descriptor("plugin_probe", PLUGIN_PROBE_DESCRIPTOR)
    validate_descriptor_against_registry(
        PLUGIN_PROBE_DESCRIPTOR,
        capability_registry,
    )

    # ── 4.6d M4 Cognitive Application（独立装配，不接默认 API/Root Graph）──
    from bdlh_runtime.cognitive.orchestrator import CognitiveOrchestrator
    from bdlh_runtime.cognitive.semantic_router import (
        SemanticRouteSelector,
        build_kernel_router,
    )
    from bdlh_runtime.domains.dispatcher import DomainDispatcher
    from bdlh_runtime.domains.finance.cognitive_adapter import (
        FinanceCognitiveContinuation,
        FinanceCognitiveSelector,
        InMemoryVerifiedEntityStore,
    )

    verified_entities = InMemoryVerifiedEntityStore()
    # 语义路由只做内核快路径；未命中再交给领域选择器，不在这里点名 Skill。
    cognitive_selector = SemanticRouteSelector(
        build_kernel_router(),
        fallback=FinanceCognitiveSelector(verified_entities),
        knowledge_responder=direct_response_model,
    )
    cognitive_application = CognitiveOrchestrator(
        selector=cognitive_selector,
        dispatcher=DomainDispatcher(domain_registry),
        continuation=FinanceCognitiveContinuation(verified_entities),
        enabled_domains=frozenset({"finance"}),
        authorized_operations=frozenset(
            {
                "READ_MARKET_DATA",
                "READ_PUBLIC_RESEARCH",
                "READ_PORTFOLIO",
                "READ_PROFILE",
                "READ_FINANCIAL_GOALS",
                "RUN_ANALYSIS",
            }
        ),
    )

    # ── 4.6e M0 关键持久化：Run Registry / Analysis History / Chat Store ──
    from .chat_sessions import InMemoryChatSessionStore, create_chat_session_store
    from .history import InMemoryAnalysisHistoryStore, create_history_store
    from .run_registry import InMemoryRunRegistry, create_run_registry

    history_store = create_history_store(
        environment=settings.environment,
        postgres_dsn=settings.postgres_dsn,
    )
    run_registry = create_run_registry(
        environment=settings.environment,
        postgres_dsn=settings.postgres_dsn,
    )
    chat_session_store = create_chat_session_store(
        environment=settings.environment,
        postgres_dsn=settings.postgres_dsn,
    )
    # M5 灰度要求 Run Registry、Analysis History、Chat Store 均为非内存实现。
    # 云上联调只要配置了 POSTGRES_DSN，上述工厂会一律返回 PG 实现。
    # Cognitive VerifiedEntityStore 仍为进程内短生命周期上下文，不计入该门禁。
    production_storage_ready = not (
        isinstance(run_registry, InMemoryRunRegistry)
        or isinstance(history_store, InMemoryAnalysisHistoryStore)
        or isinstance(chat_session_store, InMemoryChatSessionStore)
    )

    # ── 4.6f M5 灰度路由（默认 OFF，生产门禁未满足时 fail-fast）──
    from bdlh_runtime.runtime.rollout import RolloutMetrics, build_rollout_router

    traffic_router = build_rollout_router(
        settings,
        production_storage_ready=production_storage_ready,
    )
    rollout_metrics = RolloutMetrics()

    # ── 4.6g M6 最小持续任务（价格条件观察）──
    from .scheduler import (
        FinancialTaskScheduler,
        FinancialTaskWakeupHandler,
        NotificationOutboxWorker,
    )
    from .tasks import create_notification_outbox, create_task_store

    task_store = create_task_store(
        environment=settings.environment,
        postgres_dsn=settings.postgres_dsn,
    )
    notification_outbox = create_notification_outbox(
        environment=settings.environment,
        postgres_dsn=settings.postgres_dsn,
    )
    task_wakeup_handler = FinancialTaskWakeupHandler(
        task_store=task_store,
        outbox=notification_outbox,
        cognitive=cognitive_application,
    )
    task_scheduler = FinancialTaskScheduler(
        task_store=task_store,
        wakeup_handler=task_wakeup_handler,
    )
    notification_outbox_worker = NotificationOutboxWorker(
        outbox=notification_outbox,
    )

    # ── 5. Root Graph（注入全部组件）──
    graph = build_root_graph(
        checkpointer=checkpointer,
        memory_store=memory_store,
        query_agent=query_agent,
        direct_response_model=direct_response_model,
        summary_model=summary_model,
        gateway_adapter=gateway_adapter,
        research_agent=research_agent,
        llm_research_agent=llm_research_agent,
        java_adapter=java_adapter,
        context_builder=context_builder,
        analysis_capability=analysis_capability,
        web_search_adapter=web_search_adapter,
        history_store=history_store,
        capability_registry=capability_registry,
    )

    return AgentRuntimeApplication(
        settings=settings,
        graph=graph,
        checkpointer=checkpointer,
        llm=llm,
        memory_store=memory_store,
        gateway_adapter=gateway_adapter,
        query_agent=query_agent,
        direct_response_model=direct_response_model,
        summary_model=summary_model,
        research_agent=research_agent,
        llm_research_agent=llm_research_agent,
        analysis_capability=analysis_capability,
        web_search_adapter=web_search_adapter,
        history_store=history_store,
        run_registry=run_registry,
        chat_session_store=chat_session_store,
        capability_registry=capability_registry,
        domain_registry=domain_registry,
        finance_runtime=finance_runtime,
        cognitive_application=cognitive_application,
        traffic_router=traffic_router,
        rollout_metrics=rollout_metrics,
        task_store=task_store,
        notification_outbox=notification_outbox,
        task_scheduler=task_scheduler,
        notification_outbox_worker=notification_outbox_worker,
    )


def _create_memory(settings: Settings) -> Any:
    """创建记忆存储，Mem0 不可用时降级 NoOp。"""
    from bdlh_runtime.memory.mem0.mem0_store import create_memory_store

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
    from bdlh_runtime.integrations.mcp.adapter import create_adapter_from_settings

    return create_adapter_from_settings(settings)


def _create_java_adapter(base_url: str | None, *, production: bool, token: str | None) -> Any:
    """创建 Java 数据适配器（Phase 4，审查文档 §5.3）。

    base_url 未配置时：开发环境 mock 降级（带 is_mock 标记），生产环境
    返回 UNAVAILABLE（不伪造持仓结论）。
    """
    from bdlh_runtime.tools.java_data_adapter import create_java_adapter

    return create_java_adapter(base_url=base_url, production=production, token=token)


def _create_web_search_adapter(settings: Settings) -> Any:
    """创建 web-search 适配器（架构文档 §13.4）。

    base_url 未配置时：开发环境 mock 降级（带 is_mock 标记），生产环境
    返回 UNAVAILABLE（不伪造搜索结果）。
    """
    from bdlh_runtime.tools.web_search_adapter import create_web_search_adapter

    return create_web_search_adapter(
        base_url=settings.web_search_base_url,
        timeout_seconds=settings.web_search_timeout_seconds,
        production=(settings.environment == "production"),
        agent_id=settings.web_search_agent_id,
        token=settings.web_search_token,
    )


def _create_context_builder(capability_registry: Any, *, memory_store: Any) -> Any:
    """创建 ContextBuilder（审查文档 §4.4）。

    工具清单从 CapabilityRegistry 组装（确定性）；ContextBuilder 本身不做 I/O，
    Memory 召回内容由 load_memory 节点写入 state 后传入。
    """
    from bdlh_runtime.runtimes.langgraph.context import ContextBuilder, ContextService
    tool_manifest = [spec.manifest() for spec in capability_registry.list()]
    return ContextService(
        builder=ContextBuilder(tool_manifest=tool_manifest),
        memory_store=memory_store,
    )
