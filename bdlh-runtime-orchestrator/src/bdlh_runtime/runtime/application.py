"""应用装配入口。

负责把 LLM、Memory、Gateway、Finance Runtime 与 Cognitive Orchestrator 按配置
装配为唯一产品执行路径。装配原则：每个组件都走"有配置用真实版、无配置降级"
的路径，保证应用在任何环境（无 API Key、无 Mem0、无 MCP）都能启动并跑通流程。

Cognitive + Finance 是默认且唯一的编排入口；不再装配 Root Graph 产品路径。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bdlh_runtime.config import Settings
from bdlh_runtime.runtimes.langgraph.agents.direct_response_model import create_direct_response_model

from .errors import ConfigurationError
from .llm import create_llm
from .run_state import InMemoryRunStateReader


@dataclass
class AgentRuntimeApplication:
    """已装配的应用实例，持有 Cognitive 编排器与支撑组件。"""

    settings: Settings
    # 持有组件引用供调试和可观测性使用
    llm: Any | None = None
    memory_store: Any | None = None
    gateway_adapter: Any | None = None
    direct_response_model: Any | None = None
    analysis_capability: Any | None = None
    web_search_adapter: Any | None = None
    deep_research_executor: Any | None = None
    history_store: Any | None = None
    run_registry: Any | None = None
    chat_session_store: Any | None = None
    # 运行状态读写端口；内存实现仅用于显式测试环境。
    run_state_reader: Any = field(default_factory=InMemoryRunStateReader)
    capability_registry: Any | None = None
    domain_registry: Any | None = None
    finance_runtime: Any | None = None
    cognitive_application: Any | None = None
    task_store: Any | None = None
    notification_outbox: Any | None = None
    task_scheduler: Any | None = None
    notification_outbox_worker: Any | None = None
    run_control: Any | None = None


def create_application(
    settings: Settings | None = None,
    *,
    registry_snapshot: Any | None = None,
) -> AgentRuntimeApplication:
    """从 Settings 装配完整应用。

    装配顺序：LLM → Memory → Gateway → Agents → Finance → Cognitive。
    产品路径按生产标准 fail-closed（G3）：缺 Java/凭证则拒绝启动，不走 mock。
    仅 ``environment=test`` 允许注入 snapshot / 假依赖。
    """
    settings = settings or Settings.from_environment()
    if settings.auth_required and not settings.jwt_secret:
        raise ConfigurationError("启用用户隔离时必须配置 JWT_SECRET")
    if settings.environment != "test" and not settings.java_api_base_url:
        raise ConfigurationError("当前终态要求配置 JAVA_API_BASE_URL；不再支持 Python 本地数据存储回退")
    if settings.environment != "test" and not settings.java_data_internal_token:
        raise ConfigurationError("非测试环境必须配置 JAVA_DATA_INTERNAL_TOKEN；不允许无凭证 Java 调用")
    if settings.financial_task_worker_enabled and settings.financial_task_poll_seconds <= 0:
        raise ConfigurationError("M6 Worker 轮询间隔必须大于 0 秒")

    from .dependency_probes import assert_java_reachable_for_startup

    assert_java_reachable_for_startup(settings, registry_snapshot=registry_snapshot)

    # ── 1. LLM（有 Key 用真实模型，无则 None 触发各 Agent 降级）──
    llm = create_llm(
        api_key=settings.llm_api_key,
        base_url=settings.mem0.llm_base_url,
        model=settings.mem0.llm_model,
    )

    # ── 2. 记忆层（Mem0 后端不可用时降级 NoOp）──
    memory_store = _create_memory(settings)

    # ── 3. MCP Gateway（创建 client，云端不在线时调用会失败但启动不阻断）──
    gateway_adapter = _create_gateway(settings)

    # ── 4. Direct response（Cognitive knowledge_responder；按 LLM 有无降级）──
    direct_response_model = create_direct_response_model(llm)

    # ── 4.5 Java 数据适配器（Phase 4：持仓/账户/风控画像）──
    java_adapter = _create_java_adapter(
        settings.java_api_base_url,
        token=settings.java_data_internal_token,
    )

    # ── 4.5b web-search 适配器（网络搜索，HTTP 非 MCP）──
    web_search_adapter = _create_web_search_adapter(settings)

    # ── 4.5c Deep Research（ADR-016/G6：Flag + 百炼原子搜索门禁）──
    from bdlh_runtime.tools.deep_research.factory import (
        create_deep_research_executor,
        deep_research_infra_ready,
    )

    deep_infra_ready = deep_research_infra_ready(settings)
    deep_research_executor = create_deep_research_executor(settings, llm=llm)

    # ── 4.6 注册表快照（DB 真源；测试显式注入，禁止默认清单兜底）──
    registry_snapshot = _load_registry_snapshot(settings, registry_snapshot=registry_snapshot)
    from bdlh_runtime.tools.capabilities import load_capability_registry

    capability_registry = load_capability_registry(registry_snapshot)
    from bdlh_runtime.tools.analysis_capability import create_analysis_capability

    analysis_capability = create_analysis_capability()

    # ── 4.6b Finance Runtime ──
    from bdlh_runtime.cognitive.topic_hints import topic_capabilities_for
    from bdlh_runtime.domains.finance.runtime import create_finance_runtime
    from bdlh_runtime.domains.registry import DomainRegistry
    from bdlh_runtime.registry.menu import (
        allowed_capabilities,
        apply_feature_gates,
        effective_operations,
        eligible_capabilities,
    )

    finance_runtime = create_finance_runtime(
        capability_registry=capability_registry,
        topic_capabilities={
            topic: topic_capabilities_for(topic)
            for topic in ("news", "money_flow", "industry", "web_research")
        },
        gateway_adapter=gateway_adapter,
        web_search_adapter=web_search_adapter,
        analysis_capability=analysis_capability,
        java_adapter=java_adapter,
        deep_research_executor=deep_research_executor,
        deep_research_enabled=settings.deep_research_enabled and deep_infra_ready,
        execution_environment=(
            settings.environment
            if settings.environment in {"production", "development", "test"}
            else "production"
        ),
    )
    domain_registry = DomainRegistry()
    domain_registry.register("finance", finance_runtime)

    # ── 4.6c Domain Descriptor + SkillManifest 注册与启动校验 ──
    from bdlh_runtime.domains.finance.manifests import build_finance_descriptor
    from bdlh_runtime.runtime.manifest_validation import (
        validate_descriptor_against_registry,
    )

    finance_descriptor = build_finance_descriptor(registry_snapshot)
    domain_registry.register_descriptor("finance", finance_descriptor)
    validate_descriptor_against_registry(finance_descriptor, capability_registry)

    # ── 4.6c.1 M7 第二 Domain 插件契约探针（实验性、非用户入口；不在业务种子中）──
    from bdlh_runtime.domains.plugin_probe import (
        PLUGIN_PROBE_CAPABILITY,
        PLUGIN_PROBE_DESCRIPTOR,
        PluginProbeRuntime,
    )

    domain_registry.register(
        "plugin_probe",
        PluginProbeRuntime(capability_registry),
    )
    domain_registry.register_descriptor("plugin_probe", PLUGIN_PROBE_DESCRIPTOR)
    if capability_registry.contains(PLUGIN_PROBE_CAPABILITY):
        validate_descriptor_against_registry(
            PLUGIN_PROBE_DESCRIPTOR,
            capability_registry,
        )

    # ── 4.6d Cognitive Application（唯一产品编排路径）──
    from bdlh_runtime.cognitive.orchestrator import CognitiveOrchestrator
    from bdlh_runtime.cognitive.semantic_router import (
        SemanticRouteSelector,
        build_kernel_router,
    )
    from bdlh_runtime.cognitive.understand import create_understand_model
    from bdlh_runtime.domains.dispatcher import DomainDispatcher
    from bdlh_runtime.domains.finance.cognitive_adapter import (
        FinanceCognitiveContinuation,
        FinanceCognitiveSelector,
        InMemoryVerifiedEntityStore,
    )

    from .run_control import RunControlPlane

    menu_ops = effective_operations(
        registry_snapshot,
        runtime_allowed=settings.runtime_allowed_operations,
        entitlement=settings.default_entitlement_operations,
    )
    menu_eligible = eligible_capabilities(registry_snapshot, menu_ops)
    # 装配期白名单取登录态上限；未登录能力仍靠 requires_authenticated_user 与 Gateway 拦截
    menu_allowed = apply_feature_gates(
        allowed_capabilities(menu_eligible, authenticated=True),
        deep_research_enabled=settings.deep_research_enabled,
        deep_research_infra_ready=deep_infra_ready,
    )

    run_control = RunControlPlane()
    verified_entities = InMemoryVerifiedEntityStore()
    understand_model = create_understand_model(llm)
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
        authorized_operations=frozenset(menu_ops),
        authorized_capabilities=frozenset(cap.name for cap in menu_allowed),
        pause_check=run_control.is_pause_requested,
        understand=understand_model,
    )

    # ── 4.6e 运行持久化：Java Data Plane 是唯一运行时写源 ──
    from .chat_sessions import create_chat_session_store
    from .history import create_history_store
    from .run_registry import create_run_registry

    if settings.java_api_base_url:
        from .remote_run_state import create_remote_run_state_store
        from .remote_runtime_data import create_remote_runtime_stores

        history_store, run_registry, chat_session_store = create_remote_runtime_stores(
            base_url=settings.java_api_base_url,
            internal_token=settings.java_data_internal_token,
        )
        run_state_reader = create_remote_run_state_store(
            base_url=settings.java_api_base_url,
            internal_token=settings.java_data_internal_token,
        )
    else:
        # Isolated unit tests may exercise domain assembly without a Java service.
        # This branch is intentionally unavailable to development and production.
        history_store = create_history_store(environment=settings.environment)
        run_registry = create_run_registry(environment=settings.environment)
        chat_session_store = create_chat_session_store(environment=settings.environment)
        run_state_reader = InMemoryRunStateReader()

    from .chat_sessions import ChatSessionVerifiedEntityPersistence

    verified_entities.attach_persistence(ChatSessionVerifiedEntityPersistence(chat_session_store))
    # ── 4.6g M6 最小持续任务（价格条件观察）──
    from .scheduler import (
        FinancialTaskScheduler,
        FinancialTaskWakeupHandler,
        NotificationOutboxWorker,
    )

    if settings.java_api_base_url:
        from .remote_tasks import create_remote_task_stores

        task_store, notification_outbox = create_remote_task_stores(
            base_url=settings.java_api_base_url,
            internal_token=settings.java_data_internal_token,
        )
    else:
        from .tasks import create_notification_outbox, create_task_store

        task_store = create_task_store(environment=settings.environment)
        notification_outbox = create_notification_outbox(environment=settings.environment)
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

    return AgentRuntimeApplication(
        settings=settings,
        llm=llm,
        memory_store=memory_store,
        gateway_adapter=gateway_adapter,
        direct_response_model=direct_response_model,
        analysis_capability=analysis_capability,
        web_search_adapter=web_search_adapter,
        deep_research_executor=deep_research_executor,
        history_store=history_store,
        run_registry=run_registry,
        chat_session_store=chat_session_store,
        run_state_reader=run_state_reader,
        capability_registry=capability_registry,
        domain_registry=domain_registry,
        finance_runtime=finance_runtime,
        cognitive_application=cognitive_application,
        task_store=task_store,
        notification_outbox=notification_outbox,
        task_scheduler=task_scheduler,
        notification_outbox_worker=notification_outbox_worker,
        run_control=run_control,
    )


def _load_registry_snapshot(settings: Settings, *, registry_snapshot: Any | None) -> Any:
    """注册表快照：测试显式注入优先；运行时仅从 Java Data Plane 加载。

    禁止 Python 直连 registry schema、运行时 DDL/seed 与内置目录兜底。
    """
    if registry_snapshot is not None:
        return registry_snapshot
    if not settings.java_api_base_url or not settings.java_data_internal_token:
        raise ConfigurationError("Registry 快照需要 JAVA_API_BASE_URL 与 JAVA_DATA_INTERNAL_TOKEN")
    from bdlh_runtime.registry import create_remote_registry_store, load_and_validate

    store = create_remote_registry_store(
        base_url=settings.java_api_base_url,
        internal_token=settings.java_data_internal_token,
    )
    return load_and_validate(
        store,
        runtime_allowed_operations=settings.runtime_allowed_operations,
    )


def _create_memory(settings: Settings) -> Any:
    """创建 L3 Memory Port；生产不再在 Orchestrator 内实例化 Mem0 SDK。"""
    from bdlh_runtime.memory.noop import NoOpMemoryStore

    if settings.memory_mode == "noop":
        return NoOpMemoryStore()
    if settings.memory_mode == "remote":
        if not settings.memory_service_base_url or not settings.memory_service_internal_token:
            raise ConfigurationError("Remote Memory Service 需要 MEMORY_SERVICE_BASE_URL 与 MEMORY_SERVICE_INTERNAL_TOKEN")
        from bdlh_runtime.memory.remote import RemoteMemoryStore
        from bdlh_runtime.runtime.remote_runtime_data import RuntimeDataClient

        if not settings.java_api_base_url or not settings.java_data_internal_token:
            raise ConfigurationError("Remote Memory Store 写入 Outbox 需要 Java Data Plane 服务凭证")
        return RemoteMemoryStore(
            base_url=settings.memory_service_base_url,
            internal_token=settings.memory_service_internal_token,
            java_client=RuntimeDataClient(
                base_url=settings.java_api_base_url,
                internal_token=settings.java_data_internal_token,
            ),
        )
    if settings.memory_mode == "embedded-test" and settings.environment == "test":
        from bdlh_runtime.memory.mem0.mem0_store import create_memory_store

        return create_memory_store(
            mem0_llm_model=settings.mem0.llm_model,
            mem0_llm_api_key=settings.mem0.llm_api_key,
            mem0_llm_base_url=settings.mem0.llm_base_url,
            mem0_embedder_model=settings.mem0.embedder_model,
            mem0_embedder_api_key=settings.mem0.embedder_api_key,
            mem0_embedder_base_url=settings.mem0.embedder_base_url,
        )
    raise ConfigurationError("BDLH_MEMORY_MODE 只允许 noop、remote；embedded-test 仅 environment=test")


def _create_gateway(settings: Settings) -> Any:
    """创建 MCP Gateway Adapter。

    Gateway 客户端在启动时装配；首次调用再探测连通性。
    MCP 不可达不得 mock 成功 Observation（G3）。
    """
    from bdlh_runtime.integrations.mcp.adapter import create_adapter_from_settings

    return create_adapter_from_settings(settings)


def _create_java_adapter(base_url: str | None, *, token: str | None) -> Any:
    """创建 Java 数据适配器。未配置或失败一律 UNAVAILABLE，不 mock（G3）。"""
    from bdlh_runtime.tools.java_data_adapter import create_java_adapter

    return create_java_adapter(base_url=base_url, token=token)


def _create_web_search_adapter(settings: Settings) -> Any:
    """创建 web-search 适配器。未配置或失败一律 UNAVAILABLE，不 mock（G3）。"""
    from bdlh_runtime.tools.web_search_adapter import create_web_search_adapter

    return create_web_search_adapter(
        base_url=settings.web_search_base_url,
        timeout_seconds=settings.web_search_timeout_seconds,
        agent_id=settings.web_search_agent_id,
        token=settings.web_search_token,
    )
