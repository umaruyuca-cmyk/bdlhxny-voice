"""Tests-only application assembly — **not** the product path.

Use ``build_isolated_application`` for unit/API tests that must exercise HTTP
routes or Cognitive wiring **without** ``create_application`` production
fail-closed gates (Java / LLM / Qwen / Remote Memory).

Product startup remains ``bdlh_runtime.runtime.application.create_application``.
"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.config import Settings
from bdlh_runtime.runtime.application import AgentRuntimeApplication
from bdlh_runtime.runtime.chat_sessions import InMemoryChatSessionStore
from bdlh_runtime.runtime.history import InMemoryAnalysisHistoryStore
from bdlh_runtime.runtime.run_control import RunControlPlane
from bdlh_runtime.runtime.run_registry import InMemoryRunRegistry
from bdlh_runtime.runtime.run_state import InMemoryRunStateReader
from bdlh_runtime.runtime.tasks import InMemoryNotificationOutbox, InMemoryTaskStore
from tests.helpers_direct_response import DeterministicDirectResponseModel
from tests.helpers_encoder import LexicalEncoder
from tests.helpers_memory import StubMemoryStore
from tests.helpers_registry import seeded_snapshot
from tests.helpers_understand import RuleBasedUnderstandModel


def build_isolated_application(
    *,
    settings: Settings | None = None,
    registry_snapshot: Any | None = None,
    cognitive_application: Any | None = None,
) -> AgentRuntimeApplication:
    """Assemble ``AgentRuntimeApplication`` with in-memory stores and offline cognitive.

    - InMemory history / run_registry / chat_sessions / tasks / outbox / run_state
    - seeded Registry snapshot (or caller-provided)
    - ``StubMemoryStore`` (not product remote memory)
    - LexicalEncoder fastpath + DeterministicDirectResponse + RuleBasedUnderstand
    - ``execution_environment="production"`` only
    - Caller may replace ``cognitive_application`` after return (common in API tests)
    """
    settings = settings or Settings(
        environment="production",
        auth_required=False,
        memory_mode="remote",
    )
    snapshot = registry_snapshot if registry_snapshot is not None else seeded_snapshot()

    from bdlh_runtime.cognitive.goal_action_selector import GoalActionSelector
    from bdlh_runtime.cognitive.orchestrator import CognitiveOrchestrator
    from bdlh_runtime.cognitive.semantic_router import (
        SemanticRouteSelector,
        build_kernel_router,
    )
    from bdlh_runtime.cognitive.topic_hints import topic_capabilities_for
    from bdlh_runtime.domains.dispatcher import DomainDispatcher
    from bdlh_runtime.domains.finance.cognitive_adapter import (
        FinanceCognitiveContinuation,
        FinanceCognitiveSelector,
        InMemoryVerifiedEntityStore,
    )
    from bdlh_runtime.domains.finance.manifests import build_finance_descriptor
    from bdlh_runtime.domains.finance.runtime import create_finance_runtime
    from bdlh_runtime.domains.registry import DomainRegistry
    from bdlh_runtime.integrations.mcp.adapter import create_adapter_from_settings
    from bdlh_runtime.registry.menu import (
        allowed_capabilities,
        apply_feature_gates,
        effective_operations,
        eligible_capabilities,
    )
    from bdlh_runtime.runtime.chat_sessions import ChatSessionVerifiedEntityPersistence
    from bdlh_runtime.runtime.manifest_validation import validate_descriptor_against_registry
    from bdlh_runtime.runtime.scheduler import (
        FinancialTaskScheduler,
        FinancialTaskWakeupHandler,
        NotificationOutboxWorker,
    )
    from bdlh_runtime.tools.analysis_capability import create_analysis_capability
    from bdlh_runtime.tools.capabilities import load_capability_registry
    from bdlh_runtime.tools.deep_research.factory import (
        create_deep_research_executor,
        deep_research_infra_ready,
    )
    from bdlh_runtime.tools.java_data_adapter import create_java_adapter
    from bdlh_runtime.tools.web_search_adapter import create_web_search_adapter

    capability_registry = load_capability_registry(snapshot)
    analysis_capability = create_analysis_capability()
    gateway_adapter = create_adapter_from_settings(settings)
    java_adapter = create_java_adapter(base_url=None, token=None)
    web_search_adapter = create_web_search_adapter(
        base_url=settings.web_search_base_url,
        timeout_seconds=settings.web_search_timeout_seconds,
        agent_id=settings.web_search_agent_id,
        token=settings.web_search_token,
    )
    deep_infra_ready = deep_research_infra_ready(settings)
    deep_research_executor = create_deep_research_executor(settings, llm=None)

    finance_runtime = create_finance_runtime(
        capability_registry=capability_registry,
        topic_capabilities={
            topic: topic_capabilities_for(topic) for topic in ("news", "money_flow", "industry", "web_research")
        },
        gateway_adapter=gateway_adapter,
        web_search_adapter=web_search_adapter,
        analysis_capability=analysis_capability,
        java_adapter=java_adapter,
        deep_research_executor=deep_research_executor,
        deep_research_enabled=settings.deep_research_enabled and deep_infra_ready,
        execution_environment="production",
    )
    domain_registry = DomainRegistry()
    domain_registry.register("finance", finance_runtime)
    finance_descriptor = build_finance_descriptor(snapshot)
    domain_registry.register_descriptor("finance", finance_descriptor)
    validate_descriptor_against_registry(finance_descriptor, capability_registry)

    menu_ops = effective_operations(
        snapshot,
        runtime_allowed=settings.runtime_allowed_operations,
        entitlement=settings.default_entitlement_operations,
    )
    menu_eligible = eligible_capabilities(snapshot, menu_ops)
    menu_allowed = apply_feature_gates(
        allowed_capabilities(menu_eligible, authenticated=True),
        deep_research_enabled=settings.deep_research_enabled,
        deep_research_infra_ready=deep_infra_ready,
    )

    direct_response_model = DeterministicDirectResponseModel()
    run_control = RunControlPlane()
    verified_entities = InMemoryVerifiedEntityStore()
    history_store = InMemoryAnalysisHistoryStore()
    run_registry = InMemoryRunRegistry()
    chat_session_store = InMemoryChatSessionStore()
    run_state_reader = InMemoryRunStateReader()
    task_store = InMemoryTaskStore()
    notification_outbox = InMemoryNotificationOutbox()
    verified_entities.attach_persistence(ChatSessionVerifiedEntityPersistence(chat_session_store))

    finance_selector = FinanceCognitiveSelector(
        verified_entities,
        knowledge_responder=direct_response_model,
    )
    cognitive_fastpath = SemanticRouteSelector(
        build_kernel_router(encoder=LexicalEncoder()),
        knowledge_responder=direct_response_model,
    )
    wired_cognitive = CognitiveOrchestrator(
        selector=GoalActionSelector(
            finance=finance_selector,
            respond=direct_response_model,
        ),
        fastpath=cognitive_fastpath,
        dispatcher=DomainDispatcher(domain_registry),
        continuation=FinanceCognitiveContinuation(verified_entities),
        enabled_domains=frozenset({"finance"}),
        authorized_operations=frozenset(menu_ops),
        authorized_capabilities=frozenset(cap.name for cap in menu_allowed),
        pause_check=run_control.is_pause_requested,
        understand=RuleBasedUnderstandModel(),
    )
    if cognitive_application is not None:
        wired_cognitive = cognitive_application

    task_wakeup_handler = FinancialTaskWakeupHandler(
        task_store=task_store,
        outbox=notification_outbox,
        cognitive=wired_cognitive,
    )
    task_scheduler = FinancialTaskScheduler(
        task_store=task_store,
        wakeup_handler=task_wakeup_handler,
    )
    notification_outbox_worker = NotificationOutboxWorker(outbox=notification_outbox)

    return AgentRuntimeApplication(
        settings=settings,
        llm=None,
        memory_store=StubMemoryStore(),
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
        cognitive_application=wired_cognitive,
        task_store=task_store,
        notification_outbox=notification_outbox,
        task_scheduler=task_scheduler,
        notification_outbox_worker=notification_outbox_worker,
        run_control=run_control,
    )
