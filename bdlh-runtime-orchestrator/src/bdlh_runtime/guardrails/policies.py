"""M4 四时点 Guardrail 的最小可执行策略。"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.cognitive.contracts import CognitiveAction, PublicResponse

from .contracts import GuardrailContext, GuardrailDecision, GuardrailResult, GuardrailStage


class DefaultPlanGuardrail:
    def evaluate_plan(self, plan: CognitiveAction, *, context: GuardrailContext) -> GuardrailResult[CognitiveAction]:
        if not context.read_only:
            return _block(GuardrailStage.PLAN, "PLAN_READ_ONLY_REQUIRED", "PLAN-READ-ONLY-001", "当前运行不是只读模式")
        if plan.action_type.value not in context.enabled_actions:
            return _block(GuardrailStage.PLAN, "ACTION_NOT_ENABLED", "PLAN-ACTION-001", "该行动当前未启用")
        return _allow(GuardrailStage.PLAN)


class DefaultActionGuardrail:
    def evaluate_action(self, action: CognitiveAction, *, context: GuardrailContext) -> GuardrailResult[CognitiveAction]:
        if action.action_type.value not in context.enabled_actions:
            return _block(GuardrailStage.ACTION, "ACTION_NOT_ENABLED", "ACTION-ALLOWLIST-001", "该行动当前未启用")
        if action.domain_request is not None and not action.domain_request.authorized_operations:
            return _block(GuardrailStage.ACTION, "DOMAIN_AUTHORIZATION_REQUIRED", "ACTION-AUTH-001", "领域调用缺少授权范围")
        return _allow(GuardrailStage.ACTION)


class DefaultDataQualityGuardrail:
    def evaluate_data_quality(self, observation: Any, *, context: GuardrailContext) -> GuardrailResult[Any]:
        data = observation.model_dump() if hasattr(observation, "model_dump") else observation
        if not isinstance(data, dict):
            return _block(GuardrailStage.DATA_QUALITY, "DATA_CONTRACT_INVALID", "DATA-CONTRACT-001", "数据结果不符合结构化契约")
        if str(data.get("status", "SUCCESS")) in {"FAILED", "UNAVAILABLE"}:
            return _block(GuardrailStage.DATA_QUALITY, "DATA_UNAVAILABLE", "DATA-STATUS-001", "所需数据当前不可用")
        mode = str(data.get("data_mode", ""))
        if mode in {"MOCK", "TEST_FIXTURE"}:
            return _block(GuardrailStage.DATA_QUALITY, "NON_PRODUCTION_DATA", "DATA-AUTHENTICITY-001", "测试或模拟数据不能支撑真实结论")
        return _allow(GuardrailStage.DATA_QUALITY)


class DefaultResponseGuardrail:
    _TRADING_TERMS = ("立即买入", "立即卖出", "下单", "调仓", "保证收益", "稳赚")

    def evaluate_response(self, response: PublicResponse, *, context: GuardrailContext) -> GuardrailResult[PublicResponse]:
        if any(term in response.message for term in self._TRADING_TERMS):
            return _block(GuardrailStage.RESPONSE, "TRADING_SEMANTICS_BLOCKED", "RESPONSE-READ-ONLY-001", "回复包含被禁止的交易或收益承诺语义")
        if response.response_kind == "DOMAIN_RESULT" and not response.evidence_refs:
            return _block(GuardrailStage.RESPONSE, "EVIDENCE_REQUIRED", "RESPONSE-EVIDENCE-001", "领域结论必须携带可追溯证据")
        return _allow(GuardrailStage.RESPONSE)


def _allow(stage: GuardrailStage) -> GuardrailResult[Any]:
    return GuardrailResult(stage=stage, decision=GuardrailDecision.ALLOW)


def _block(stage: GuardrailStage, code: str, rule_id: str, reason: str) -> GuardrailResult[Any]:
    return GuardrailResult(
        stage=stage, decision=GuardrailDecision.BLOCK, audit_code=code, rule_ids=[rule_id], reasons=[reason]
    )
