"""领域无关的分发边界，供 Cognitive 运行时调用。"""

from __future__ import annotations

import inspect
from typing import Any, Protocol, runtime_checkable

from bdlh_runtime.domains.contracts import (
    ConfidenceAssessment,
    DomainError,
    DomainOutcome,
    DomainRequest,
)

from .registry import DomainRegistry


@runtime_checkable
class DomainRuntime(Protocol):
    async def run(self, request: DomainRequest) -> DomainOutcome: ...


class DomainDispatcher:
    """只路由已注册领域，并将边界失败规范化为 DomainOutcome。"""

    def __init__(self, registry: DomainRegistry) -> None:
        self._registry = registry

    async def dispatch(self, request: DomainRequest) -> DomainOutcome:
        if not self._registry.contains(request.domain):
            return self._failed(request, "DOMAIN_NOT_REGISTERED", "Requested domain is not registered")
        runtime: Any = self._registry.get(request.domain)
        runner = getattr(runtime, "run", None)
        if not callable(runner):
            return self._failed(request, "DOMAIN_RUNTIME_INVALID", "Registered domain has no run entrypoint")
        try:
            outcome = runner(request)
            if inspect.isawaitable(outcome):
                outcome = await outcome
        except Exception as exc:
            return self._failed(
                request, "DOMAIN_DISPATCH_FAILED", f"Domain execution failed: {type(exc).__name__}", retryable=True
            )
        if not isinstance(outcome, DomainOutcome):
            return self._failed(request, "DOMAIN_CONTRACT_VIOLATION", "Domain runtime did not return DomainOutcome")
        if outcome.request_id != request.request_id or outcome.domain != request.domain:
            return self._failed(request, "DOMAIN_CONTRACT_VIOLATION", "Domain outcome identity mismatch")
        return outcome

    @staticmethod
    def _failed(request: DomainRequest, code: str, message: str, *, retryable: bool = False) -> DomainOutcome:
        return DomainOutcome(
            request_id=request.request_id,
            domain=request.domain,
            status="FAILED",
            confidence=ConfidenceAssessment(level="LOW", reasons=[message], coverage_status="LIMITED"),
            errors=[DomainError(code=code, message=message, retryable=retryable)],
            limitations=[message],
        )
