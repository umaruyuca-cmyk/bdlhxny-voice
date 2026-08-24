"""金融域 Plan Guardrail：只读入口禁止交易语义。"""

from __future__ import annotations

from bdlh_runtime.cognitive.contracts import CognitiveAction
from bdlh_runtime.guardrails.contracts import GuardrailContext, GuardrailDecision, GuardrailResult, GuardrailStage


class FinanceReadOnlyPlanGuardrail:
    _PROHIBITED = (
        "下单",
        "买入",
        "卖出",
        "调仓",
        "transfer",
        "place order",
        "execute trade",
    )

    def evaluate_plan(self, plan: CognitiveAction, *, context: GuardrailContext) -> GuardrailResult[CognitiveAction]:
        del context
        request = plan.domain_request
        if request is None:
            return GuardrailResult(stage=GuardrailStage.PLAN, decision=GuardrailDecision.ALLOW)
        objective = request.objective.lower()
        if any(term in objective for term in self._PROHIBITED):
            return GuardrailResult(
                stage=GuardrailStage.PLAN,
                decision=GuardrailDecision.BLOCK,
                audit_code="PLAN_OUT_OF_READ_ONLY_SCOPE",
                rule_ids=["PLAN-SCOPE-001"],
                reasons=["当前入口只允许只读研究与分析"],
            )
        return GuardrailResult(stage=GuardrailStage.PLAN, decision=GuardrailDecision.ALLOW)
