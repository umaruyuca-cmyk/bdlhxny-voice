"""域插件装配契约。装配层按 Registry 域集合挂载，不在内核写死域名单。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bdlh_runtime.cognitive.contracts import CognitiveAction, CommunicationPlan, InputEvent
from bdlh_runtime.domains.contracts import DomainOutcome
from bdlh_runtime.domains.manifests import DomainDescriptor


@dataclass(frozen=True)
class DomainPlugin:
    """单个 Domain 对装配层暴露的可插拔切片。"""

    domain: str
    runtime: Any
    descriptor: DomainDescriptor
    selector: Any
    continuation: Any | None = None
    plan_guardrail: Any | None = None
    entity_store: Any | None = None


class DomainContinuationRouter:
    """按 outcome.domain 分发给各域 continuation；未注册则返回 None 走通用表达。"""

    def __init__(self, by_domain: dict[str, Any]) -> None:
        self._by_domain = dict(by_domain)

    async def continue_after(
        self,
        *,
        event: InputEvent,
        outcome: DomainOutcome,
    ) -> CognitiveAction | CommunicationPlan | None:
        handler = self._by_domain.get(outcome.domain)
        if handler is None:
            return None
        return await handler.continue_after(event=event, outcome=outcome)
