"""Finance 域插件入口。"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.cognitive.topic_hints import topic_capabilities_for
from bdlh_runtime.domains.finance.cognitive_adapter import (
    FinanceCognitiveContinuation,
    FinanceCognitiveSelector,
    InMemoryVerifiedEntityStore,
)
from bdlh_runtime.domains.finance.manifests import build_finance_descriptor
from bdlh_runtime.domains.finance.plan_guardrail import FinanceReadOnlyPlanGuardrail
from bdlh_runtime.domains.finance.runtime import create_finance_runtime
from bdlh_runtime.domains.plugin import DomainPlugin


def install_finance(ctx: Any) -> DomainPlugin:
    runtime = create_finance_runtime(
        capability_registry=ctx.capability_registry,
        topic_capabilities={
            topic: topic_capabilities_for(topic) for topic in ("news", "money_flow", "industry", "web_research")
        },
        gateway_adapter=ctx.gateway_adapter,
        web_search_adapter=ctx.web_search_adapter,
        analysis_capability=ctx.analysis_capability,
        java_adapter=ctx.java_adapter,
        deep_research_executor=ctx.deep_research_executor,
        deep_research_enabled=ctx.deep_research_enabled,
        execution_environment=ctx.execution_environment,
    )
    entity_store = InMemoryVerifiedEntityStore()
    selector = FinanceCognitiveSelector(
        entity_store,
        knowledge_responder=ctx.knowledge_responder,
    )
    return DomainPlugin(
        domain="finance",
        runtime=runtime,
        descriptor=build_finance_descriptor(ctx.snapshot),
        selector=selector,
        continuation=FinanceCognitiveContinuation(entity_store),
        plan_guardrail=FinanceReadOnlyPlanGuardrail(),
        entity_store=entity_store,
    )
