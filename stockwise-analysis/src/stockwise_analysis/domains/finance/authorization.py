"""M1/M3 Finance Runtime 的精确 Capability 授权策略。"""

from __future__ import annotations

from dataclasses import dataclass

from stockwise_analysis.contracts.data_requirements import DataRequirement
from stockwise_analysis.domains.contracts import DomainOperation
from stockwise_analysis.tools.capabilities import CapabilityRegistry


ANALYSIS_CAPABILITY = "analysis.run_analysis"


M1_OPERATION_CAPABILITIES: dict[DomainOperation, frozenset[str]] = {
    DomainOperation.READ_MARKET_DATA: frozenset({
        "market.resolve_instrument",
        "market.get_realtime_quote",
        "market.get_historical_prices",
        "market.get_financial_statements",
        "market.get_valuation",
        "market.get_industry_context",
        "market.get_money_flow",
        "market.get_news",
    }),
    DomainOperation.READ_PUBLIC_RESEARCH: frozenset({"research.web_search"}),
    DomainOperation.RUN_ANALYSIS: frozenset({ANALYSIS_CAPABILITY}),
}

M3_OPERATION_CAPABILITIES: dict[DomainOperation, frozenset[str]] = {
    DomainOperation.READ_PORTFOLIO: frozenset({
        "portfolio.get_current_positions",
        "portfolio.get_account_snapshot",
    }),
    DomainOperation.READ_PROFILE: frozenset({"user.get_risk_profile"}),
}

FINANCE_OPERATION_CAPABILITIES = {
    **M1_OPERATION_CAPABILITIES,
    **M3_OPERATION_CAPABILITIES,
}


@dataclass(frozen=True)
class AuthorizationDecision:
    """一次确定性授权过滤结果。"""

    allowed_requirements: tuple[DataRequirement, ...]
    missing_required: tuple[str, ...]
    skipped_optional: tuple[str, ...]


class FinanceCapabilityAuthorizationPolicy:
    """将领域操作映射为 Registry 中的精确只读 Capability。"""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry
        configured = set().union(*FINANCE_OPERATION_CAPABILITIES.values())
        missing = sorted(name for name in configured if not registry.contains(name))
        if missing:
            raise ValueError(
                "Finance authorization references unregistered capabilities: "
                + ", ".join(missing)
            )

    def allowed_capabilities(
        self,
        operations: set[DomainOperation],
    ) -> frozenset[str]:
        allowed: set[str] = set()
        for operation in operations:
            allowed.update(
                FINANCE_OPERATION_CAPABILITIES.get(operation, frozenset())
            )
        return frozenset(allowed)

    def is_allowed(
        self,
        capability: str,
        operations: set[DomainOperation],
    ) -> bool:
        return capability in self.allowed_capabilities(operations)

    def authorize(
        self,
        requirements: list[DataRequirement],
        operations: set[DomainOperation],
    ) -> AuthorizationDecision:
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
