"""M4 四时点 Guardrail 契约、接口与默认执行策略。"""

from .assembly import authorized_capabilities_from_registry
from .contracts import (
    GuardrailContext,
    GuardrailDecision,
    GuardrailResult,
    GuardrailStage,
)
from .data_quality_rules import evaluate_freshness, evaluate_provenance_depth
from .interfaces import (
    ActionGuardrail,
    DataQualityGuardrail,
    PlanGuardrail,
    ResponseGuardrail,
)
from .policies import (
    DefaultActionGuardrail,
    DefaultDataQualityGuardrail,
    DefaultPlanGuardrail,
    DefaultResponseGuardrail,
)
from .research_rules import (
    evaluate_research_observation,
    evaluate_research_response_text,
    plan_requires_deep_capability,
)

__all__ = [
    "ActionGuardrail",
    "DataQualityGuardrail",
    "DefaultActionGuardrail",
    "DefaultDataQualityGuardrail",
    "DefaultPlanGuardrail",
    "DefaultResponseGuardrail",
    "GuardrailContext",
    "GuardrailDecision",
    "GuardrailResult",
    "GuardrailStage",
    "PlanGuardrail",
    "ResponseGuardrail",
    "authorized_capabilities_from_registry",
    "evaluate_freshness",
    "evaluate_provenance_depth",
    "evaluate_research_observation",
    "evaluate_research_response_text",
    "plan_requires_deep_capability",
]
