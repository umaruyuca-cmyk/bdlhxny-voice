"""按 Registry 快照挂载 Domain 插件；装配代码不写死域名单。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bdlh_runtime.domains.plugin import DomainContinuationRouter, DomainPlugin
from bdlh_runtime.domains.registry import DomainRegistry
from bdlh_runtime.guardrails.policies import CompositePlanGuardrail, DefaultPlanGuardrail
from bdlh_runtime.runtime.manifest_validation import validate_descriptor_against_registry


@dataclass
class AssemblyContext:
    snapshot: Any
    capability_registry: Any
    gateway_adapter: Any = None
    web_search_adapter: Any = None
    analysis_capability: Any = None
    java_adapter: Any = None
    deep_research_executor: Any = None
    deep_research_enabled: bool = False
    execution_environment: str = "production"
    knowledge_responder: Any = None


@dataclass
class DomainAssembly:
    registry: DomainRegistry
    handlers: dict[str, Any]
    continuation: DomainContinuationRouter | None
    plan_guardrail: Any
    enabled_domains: frozenset[str]
    plugins: dict[str, DomainPlugin]

    def runtime(self, domain: str) -> Any:
        return self.plugins[domain].runtime

    @property
    def entity_store(self) -> Any:
        for plugin in self.plugins.values():
            if plugin.entity_store is not None:
                return plugin.entity_store
        return None


def _installers() -> dict[str, Callable[[AssemblyContext], DomainPlugin]]:
    from bdlh_runtime.domains.finance.plugin import install_finance
    from bdlh_runtime.domains.weather.plugin import install_weather

    return {
        "finance": install_finance,
        "weather": install_weather,
    }


def assemble_domains(ctx: AssemblyContext) -> DomainAssembly:
    """只装配快照里出现过的 domain；handlers / enabled_domains 由插件表生成。"""

    wanted = {skill.domain for skill in ctx.snapshot.skills}
    registry = DomainRegistry()
    plugins: dict[str, DomainPlugin] = {}
    for domain, installer in _installers().items():
        if domain not in wanted:
            continue
        plugin = installer(ctx)
        registry.register(plugin.domain, plugin.runtime)
        registry.register_descriptor(plugin.domain, plugin.descriptor)
        validate_descriptor_against_registry(plugin.descriptor, ctx.capability_registry)
        plugins[plugin.domain] = plugin

    handlers = {domain: plugin.selector for domain, plugin in plugins.items()}
    continuations = {
        domain: plugin.continuation for domain, plugin in plugins.items() if plugin.continuation is not None
    }
    extra_guards = tuple(plugin.plan_guardrail for plugin in plugins.values() if plugin.plan_guardrail is not None)
    return DomainAssembly(
        registry=registry,
        handlers=handlers,
        continuation=DomainContinuationRouter(continuations) if continuations else None,
        plan_guardrail=CompositePlanGuardrail(DefaultPlanGuardrail(), *extra_guards),
        enabled_domains=frozenset(plugins),
        plugins=plugins,
    )
