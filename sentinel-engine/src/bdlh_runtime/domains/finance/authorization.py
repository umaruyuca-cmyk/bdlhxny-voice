"""Finance Runtime 的精确 Capability 授权策略（重写：读库形态）。

operation→capability 映射不再硬编码（M1/M3 常量已删）；授权判断直接
反查 Registry（真源为库表 bdlh_runtime_capability_operation，经
RegistrySnapshot 派生注入）：capability 允许 ⟺ 其 required_operations
全部 ⊆ 本次请求的 authorized_operations。
"""

from __future__ import annotations

from dataclasses import dataclass

from bdlh_runtime.contracts.data_requirements import DataRequirement
from bdlh_runtime.domains.contracts import DomainOperation
from bdlh_runtime.tools.capabilities import CapabilityRegistry

ANALYSIS_CAPABILITY = "analysis.run_analysis"


@dataclass(frozen=True)
class AuthorizationDecision:
    """一次确定性授权过滤结果。"""

    allowed_requirements: tuple[DataRequirement, ...]
    missing_required: tuple[str, ...]
    skipped_optional: tuple[str, ...]


class FinanceCapabilityAuthorizationPolicy:
    """将领域操作映射为 Registry 中的精确只读 Capability（读库派生）。"""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry

    def allowed_capabilities(
        self,
        operations: set[DomainOperation],
    ) -> frozenset[str]:
        granted = set(operations)
        return frozenset(
            spec.name
            for spec in self._registry.list()
            if spec.operations  # capability_operation 表至少一行（loader 校验）
            and set(spec.operations).issubset(granted)
        )

    def is_allowed(
        self,
        capability: str,
        operations: set[DomainOperation],
    ) -> bool:
        if not self._registry.contains(capability):
            return False
        return set(self._registry.get(capability).operations).issubset(set(operations))

    def authorize(
        self,
        requirements: list[DataRequirement],
        operations: set[DomainOperation],
    ) -> AuthorizationDecision:
        """确定性授权过滤：required 缺证失败、optional 缺证降级跳过。"""
        allowed = self.allowed_capabilities(operations)
        accepted: list[DataRequirement] = []
        missing_required: list[str] = []
        skipped_optional: list[str] = []
        for requirement in requirements:
            if requirement.capability in allowed:
                accepted.append(requirement)
            elif requirement.required:
                missing_required.append(requirement.capability)
            else:
                skipped_optional.append(requirement.capability)
        return AuthorizationDecision(
            allowed_requirements=tuple(accepted),
            missing_required=tuple(missing_required),
            skipped_optional=tuple(skipped_optional),
        )
