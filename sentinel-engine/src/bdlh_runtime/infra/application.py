"""应用装配入口。

负责把 LLM、Memory、Gateway 与 ``engine/``（AgentLoop + EngineRuntime）按配置
装配为唯一产品执行路径。装配原则：生产标准 fail-closed——缺 Java / LLM /
Qwen 向量 / Remote Memory 等必需凭证则拒绝启动，不提供 mock/noop/词法逃生门。

隔离单测请用 ``tests/helpers_application.build_isolated_application``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bdlh_runtime.config import Settings

from .errors import ConfigurationError
from .llm import create_llm
from .run_state import InMemoryRunStateReader


@dataclass
class AgentRuntimeApplication:
    """已装配的应用实例，持有 engine/（EngineRuntime）与支撑组件。"""

    settings: Settings
    # 持有组件引用供调试和可观测性使用
    llm: Any | None = None
    memory_store: Any | None = None
    gateway_adapter: Any | None = None
    analysis_capability: Any | None = None
    web_search_adapter: Any | None = None
    deep_research_executor: Any | None = None
    history_store: Any | None = None
    run_registry: Any | None = None
    chat_session_store: Any | None = None
    # 运行状态读写端口；内存实现仅用于显式测试构造。
    run_state_reader: Any = field(default_factory=InMemoryRunStateReader)
    capability_registry: Any | None = None
    engine_runtime: Any | None = None
    task_store: Any | None = None
    notification_outbox: Any | None = None
    task_scheduler: Any | None = None
    notification_outbox_worker: Any | None = None
    run_control: Any | None = None
    # 看护环（T1）：事件流水与通知持久化端口，由装配注入；缺省 None 时
    # 演示注入端点与 followup 走回退路径或 503。
    watch_event_store: Any | None = None
    watch_notification_store: Any | None = None


def create_application(
    settings: Settings | None = None,
    *,
    registry_snapshot: Any | None = None,
) -> AgentRuntimeApplication:
    """从 Settings 装配完整应用（生产标准 fail-closed）。

    装配顺序：LLM → Memory → Gateway → ToolCatalog → AgentLoop。
    缺 Java/LLM/Qwen/Memory 凭证一律 ConfigurationError，不因「任意环境」放行。
    """
    settings = settings or Settings.from_environment()
    if settings.auth_required and not settings.jwt_secret:
        raise ConfigurationError("启用用户隔离时必须配置 JWT_SECRET")
    if not settings.java_api_base_url:
        raise ConfigurationError("当前终态要求配置 JAVA_API_BASE_URL；不再支持 Python 本地数据存储回退")
    if not settings.java_data_internal_token:
        raise ConfigurationError("必须配置 JAVA_DATA_INTERNAL_TOKEN；不允许无凭证 Java 调用")
    if not settings.llm_api_key:
        raise ConfigurationError("必须配置 LLM_API_KEY（或 DEEPSEEK_API_KEY）")
    if not settings.fastpath_embedder_base_url:
        raise ConfigurationError("生产快路径要求 Qwen 向量服务：请设置 QWEN3_BASE_URL / FASTPATH_EMBEDDER_BASE_URL")
    if settings.memory_mode != "remote":
        raise ConfigurationError("BDLH_MEMORY_MODE 仅支持 remote；noop/embedded-test 已从产品路径移除")
    if not settings.memory_service_base_url:
        raise ConfigurationError("Remote Memory Service 需要 MEMORY_SERVICE_BASE_URL")
    if not settings.memory_service_internal_token:
        raise ConfigurationError("Remote Memory Service 需要 MEMORY_SERVICE_INTERNAL_TOKEN")
    if settings.financial_task_worker_enabled and settings.financial_task_poll_seconds <= 0:
        raise ConfigurationError("M6 Worker 轮询间隔必须大于 0 秒")

    from .dependency_probes import assert_java_reachable_for_startup

    assert_java_reachable_for_startup(settings, registry_snapshot=registry_snapshot)

    # ── 1. LLM（缺 Key 已在上方拒绝；create_llm 仍可能因依赖缺失返回 None）──
    llm = create_llm(
        api_key=settings.llm_api_key,
        base_url=settings.mem0.llm_base_url,
        model=settings.mem0.llm_model,
    )
    if llm is None:
        raise ConfigurationError("LLM 客户端创建失败：请检查 LLM_API_KEY 与 langchain-openai 依赖")

    # ── 2. 记忆层（仅 Remote Memory Service）──
    memory_store = _create_memory(settings)

    # ── 3. MCP Gateway（创建 client，云端不在线时调用会失败但启动不阻断）──
    gateway_adapter = _create_gateway(settings)

    # ── 4.5 Java 数据适配器（持仓/账户/风控画像）──
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

    # ── 4.6 注册表快照（DB 真源；测试可显式注入，禁止默认清单兜底）──
    registry_snapshot = _load_registry_snapshot(settings, registry_snapshot=registry_snapshot)
    from bdlh_runtime.tools.capabilities import load_capability_registry

    capability_registry = load_capability_registry(registry_snapshot)
    from bdlh_runtime.tools.analysis_capability import create_analysis_capability

    analysis_capability = create_analysis_capability()

    from .run_control import RunControlPlane

    run_control = RunControlPlane()
    encoder = _fastpath_encoder(settings)
    engine_runtime = build_engine_runtime(
        llm=llm,
        settings=settings,
        registry_snapshot=registry_snapshot,
        gateway_adapter=gateway_adapter,
        java_adapter=java_adapter,
        web_search_adapter=web_search_adapter,
        analysis_capability=analysis_capability,
        deep_research_executor=deep_research_executor,
        deep_research_infra_ready=deep_infra_ready,
        memory_store=memory_store,
        encoder=encoder,
        pause_check=run_control.is_pause_requested,
    )

    # ── 4.6e 运行持久化：Java Data Plane 是唯一运行时写源 ──
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

    # ── 4.6g M6 最小持续任务（价格条件观察）──
    from .remote_tasks import create_remote_task_stores
    from .scheduler import (
        FinancialTaskScheduler,
        FinancialTaskWakeupHandler,
        NotificationOutboxWorker,
    )

    task_store, notification_outbox = create_remote_task_stores(
        base_url=settings.java_api_base_url,
        internal_token=settings.java_data_internal_token,
    )
    task_wakeup_handler = FinancialTaskWakeupHandler(
        task_store=task_store,
        outbox=notification_outbox,
        cognitive=engine_runtime,
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
        analysis_capability=analysis_capability,
        web_search_adapter=web_search_adapter,
        deep_research_executor=deep_research_executor,
        history_store=history_store,
        run_registry=run_registry,
        chat_session_store=chat_session_store,
        run_state_reader=run_state_reader,
        capability_registry=capability_registry,
        engine_runtime=engine_runtime,
        task_store=task_store,
        notification_outbox=notification_outbox,
        task_scheduler=task_scheduler,
        notification_outbox_worker=notification_outbox_worker,
        run_control=run_control,
    )


def build_engine_runtime(
    *,
    llm: Any,
    settings: Settings,
    registry_snapshot: Any,
    gateway_adapter: Any,
    java_adapter: Any,
    web_search_adapter: Any,
    analysis_capability: Any,
    deep_research_executor: Any,
    deep_research_infra_ready: bool,
    memory_store: Any,
    encoder: Any,
    pause_check: Any,
) -> Any:
    """装配 ToolCatalog + AgentLoop + EngineRuntime（生产与隔离测试共用）。"""
    from bdlh_runtime.cognitive.semantic_router import build_kernel_router
    from bdlh_runtime.engine.executor import CatalogToolExecutor
    from bdlh_runtime.engine.loader import ToolLoader
    from bdlh_runtime.engine.loop import AgentLoop
    from bdlh_runtime.engine.runtime import EngineRuntime
    from bdlh_runtime.registry.menu import (
        allowed_capabilities,
        apply_feature_gates,
        effective_operations,
        eligible_capabilities,
    )
    from bdlh_runtime.tools.catalog import ToolCatalog, catalog_from_snapshot

    menu_ops = effective_operations(
        registry_snapshot,
        runtime_allowed=settings.runtime_allowed_operations,
        entitlement=settings.default_entitlement_operations,
    )
    menu_eligible = eligible_capabilities(registry_snapshot, menu_ops)
    menu_allowed = apply_feature_gates(
        allowed_capabilities(menu_eligible, authenticated=True),
        deep_research_enabled=settings.deep_research_enabled,
        deep_research_infra_ready=deep_research_infra_ready,
    )
    allowed_names = {cap.name for cap in menu_allowed}
    source = catalog_from_snapshot(registry_snapshot)
    catalog = ToolCatalog()
    for card in source.list():
        if card.name in {"memory.recall", "search_tools"} or card.name in allowed_names:
            catalog.register(card)
    loader = ToolLoader(catalog, tool_loading=settings.tool_loading, encoder=encoder)
    executor = CatalogToolExecutor(
        catalog,
        gateway_adapter=gateway_adapter,
        java_adapter=java_adapter,
        web_search_adapter=web_search_adapter,
        analysis_capability=analysis_capability,
        deep_research_executor=deep_research_executor,
        memory_store=memory_store,
    )
    loop = AgentLoop(
        llm=llm,
        catalog=catalog,
        executor=executor,
        loader=loader,
        router=build_kernel_router(encoder=encoder, score_thresholds=_fastpath_thresholds(settings)),
    )
    return EngineRuntime(
        loop,
        pause_check=pause_check,
        executor=executor,
        catalog=catalog,
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
    """创建 L3 Memory Port；产品路径仅 Remote Memory Service。"""
    if settings.memory_mode != "remote":
        raise ConfigurationError("BDLH_MEMORY_MODE 仅支持 remote；noop/embedded-test 已从产品路径移除")
    if not settings.memory_service_base_url or not settings.memory_service_internal_token:
        raise ConfigurationError("Remote Memory Service 需要 MEMORY_SERVICE_BASE_URL 与 MEMORY_SERVICE_INTERNAL_TOKEN")
    from bdlh_runtime.infra.remote_runtime_data import RuntimeDataClient
    from bdlh_runtime.memory.remote import RemoteMemoryStore

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


def _create_gateway(settings: Settings) -> Any:
    """创建 MCP Gateway Adapter。

    Gateway 客户端在启动时装配；首次调用再探测连通性。
    MCP 不可达不得 mock 成功 Observation（G3）。
    """
    from bdlh_runtime.integrations.mcp.adapter import create_adapter_from_settings

    return create_adapter_from_settings(settings)


def _fastpath_encoder(settings: Settings) -> Any:
    """快路径编码器：始终使用 Qwen 向量模型。

    启动即预编码全部样句——Qwen 服务地址配错时装配直接失败（fail-closed）。
    运行期偶发故障由 SemanticRouter 降级未命中。
    """
    from bdlh_runtime.cognitive.semantic_router.encoder import QwenEmbeddingEncoder

    assert settings.fastpath_embedder_base_url is not None  # 上方 create_application 已校验
    return QwenEmbeddingEncoder(
        base_url=settings.fastpath_embedder_base_url,
        model=settings.fastpath_embedder_model,
        api_key=settings.fastpath_embedder_api_key,
        timeout_seconds=settings.fastpath_embedder_timeout_seconds,
    )


def _fastpath_thresholds(settings: Settings) -> Any:
    """模型编码相似度空间阈值（见 fastpath_data 校准注记）。"""
    del settings
    from bdlh_runtime.cognitive.semantic_router.fastpath_data import MODEL_FASTPATH_THRESHOLDS

    return MODEL_FASTPATH_THRESHOLDS


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
