"""Tests-only application assembly — **not** the product path.

Use ``build_isolated_application`` for unit/API tests that must exercise HTTP
routes or engine wiring **without** ``create_application`` production
fail-closed gates (Java / LLM / Qwen / Remote Memory).

Product startup remains ``bdlh_runtime.infra.application.create_application``.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from bdlh_runtime.config import Settings
from bdlh_runtime.infra.application import AgentRuntimeApplication, build_engine_runtime
from bdlh_runtime.infra.chat_sessions import InMemoryChatSessionStore
from bdlh_runtime.infra.history import InMemoryAnalysisHistoryStore
from bdlh_runtime.infra.run_control import RunControlPlane
from bdlh_runtime.infra.run_registry import InMemoryRunRegistry
from bdlh_runtime.infra.run_state import InMemoryRunStateReader
from bdlh_runtime.infra.tasks import InMemoryNotificationOutbox, InMemoryTaskStore
from tests.helpers_direct_response import DeterministicDirectResponseModel
from tests.helpers_encoder import LexicalEncoder
from tests.helpers_memory import StubMemoryStore
from tests.helpers_registry import seeded_snapshot


class IsolatedChatModel:
    """隔离测试用：无真实 LLM，按确定性替身直答，不发起 tool_calls。"""

    def __init__(self, responder: Any) -> None:
        self._responder = responder

    def bind_tools(self, tools, **_kwargs):
        del tools
        return self

    async def ainvoke(self, messages, **_kwargs):
        text = ""
        for item in reversed(list(messages)):
            if isinstance(item, HumanMessage) or getattr(item, "type", "") == "human":
                text = str(getattr(item, "content", "") or "")
                break
        return AIMessage(content=self._responder.answer(text or "你好"))

    async def astream(self, messages, **kwargs):
        yield await self.ainvoke(messages, **kwargs)


def build_isolated_application(
    *,
    settings: Settings | None = None,
    registry_snapshot: Any | None = None,
    cognitive_application: Any | None = None,
    chat_model: Any | None = None,
) -> AgentRuntimeApplication:
    """Assemble ``AgentRuntimeApplication`` with in-memory stores and offline engine.

    - InMemory history / run_registry / chat_sessions / tasks / outbox / run_state
    - seeded Registry snapshot (or caller-provided)
    - ``StubMemoryStore`` (not product remote memory)
    - LexicalEncoder fastpath + IsolatedChatModel（产品路径仍 fail-closed）
    - Caller may replace ``cognitive_application`` after return (common in API tests)
    """
    settings = settings or Settings(
        environment="production",
        auth_required=False,
        memory_mode="remote",
    )
    snapshot = registry_snapshot if registry_snapshot is not None else seeded_snapshot()

    from bdlh_runtime.infra.scheduler import (
        FinancialTaskScheduler,
        FinancialTaskWakeupHandler,
        NotificationOutboxWorker,
    )
    from bdlh_runtime.integrations.mcp.adapter import create_adapter_from_settings
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
    direct_response_model = DeterministicDirectResponseModel()
    isolated_llm = chat_model if chat_model is not None else IsolatedChatModel(direct_response_model)

    run_control = RunControlPlane()
    history_store = InMemoryAnalysisHistoryStore()
    run_registry = InMemoryRunRegistry()
    chat_session_store = InMemoryChatSessionStore()
    run_state_reader = InMemoryRunStateReader()
    task_store = InMemoryTaskStore()
    notification_outbox = InMemoryNotificationOutbox()

    wired_cognitive = build_engine_runtime(
        llm=isolated_llm,
        settings=settings,
        registry_snapshot=snapshot,
        gateway_adapter=gateway_adapter,
        java_adapter=java_adapter,
        web_search_adapter=web_search_adapter,
        analysis_capability=analysis_capability,
        deep_research_executor=deep_research_executor,
        deep_research_infra_ready=deep_infra_ready,
        memory_store=StubMemoryStore(),
        encoder=LexicalEncoder(),
        pause_check=run_control.is_pause_requested,
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
        domain_registry=None,
        finance_runtime=None,
        cognitive_application=wired_cognitive,
        task_store=task_store,
        notification_outbox=notification_outbox,
        task_scheduler=task_scheduler,
        notification_outbox_worker=notification_outbox_worker,
        run_control=run_control,
    )
