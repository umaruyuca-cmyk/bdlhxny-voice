"""M4 四时点 Guardrail 的领域无关、可执行最低策略集。"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.cognitive.contracts import CognitiveAction, PublicResponse

from .contracts import GuardrailContext, GuardrailDecision, GuardrailResult, GuardrailStage
from .research_rules import (
    action_rejects_unauthorized_deep,
    evaluate_research_observation,
    evaluate_research_response_text,
    plan_requires_deep_capability,
)


class DefaultPlanGuardrail:
    def evaluate_plan(
        self, plan: CognitiveAction, *, context: GuardrailContext
    ) -> GuardrailResult[CognitiveAction]:
        if not context.read_only:
            return _block(
                GuardrailStage.PLAN,
                "PLAN_READ_ONLY_REQUIRED",
                "PLAN-READ-ONLY-001",
                "当前运行不是只读模式",
            )
        if plan.action_type.value not in context.enabled_actions:
            return _block(
                GuardrailStage.PLAN,
                "ACTION_NOT_ENABLED",
                "PLAN-ACTION-001",
                "该行动当前未启用",
            )
        request = plan.domain_request
        if request is not None:
            if request.domain not in context.enabled_domains:
                return _block(
                    GuardrailStage.PLAN,
                    "DOMAIN_NOT_ENABLED",
                    "PLAN-DOMAIN-001",
                    "请求的领域当前未启用",
                )
            if (
                request.budget.tool_call_limit > context.max_tool_calls
                or request.budget.runtime_seconds > context.max_runtime_seconds
            ):
                return _block(
                    GuardrailStage.PLAN,
                    "PLAN_BUDGET_EXCEEDED",
                    "PLAN-BUDGET-001",
                    "领域调用预算超过本轮允许上限",
                )
            prohibited = (
                "下单", "买入", "卖出", "调仓", "transfer", "place order", "execute trade",
            )
            objective = request.objective.lower()
            if any(term in objective for term in prohibited):
                return _block(
                    GuardrailStage.PLAN,
                    "PLAN_OUT_OF_READ_ONLY_SCOPE",
                    "PLAN-SCOPE-001",
                    "当前入口只允许只读研究与分析",
                )
            deep_code = plan_requires_deep_capability(
                objective=request.objective,
                success_criteria=list(request.success_criteria),
                authorized_capabilities=context.authorized_capabilities,
            )
            if deep_code:
                return _block(
                    GuardrailStage.PLAN,
                    deep_code,
                    "PLAN-RESEARCH-DEEP-001",
                    "本轮能力白名单未包含 research.deep_search，不能规划深度研究",
                )
        return _allow(GuardrailStage.PLAN)


class DefaultActionGuardrail:
    def evaluate_action(
        self, action: CognitiveAction, *, context: GuardrailContext
    ) -> GuardrailResult[CognitiveAction]:
        if action.action_type.value not in context.enabled_actions:
            return _block(
                GuardrailStage.ACTION,
                "ACTION_NOT_ENABLED",
                "ACTION-ALLOWLIST-001",
                "该行动当前未启用",
            )
        request = action.domain_request
        if request is not None and request.authenticated_user_id != context.authenticated_user_id:
            return _block(
                GuardrailStage.ACTION,
                "DOMAIN_IDENTITY_MISMATCH",
                "ACTION-IDENTITY-001",
                "领域请求身份与认证用户不一致",
            )
        if request is not None and not request.authorized_operations:
            return _block(
                GuardrailStage.ACTION,
                "DOMAIN_AUTHORIZATION_REQUIRED",
                "ACTION-AUTH-001",
                "领域调用缺少授权范围",
            )
        if request is not None:
            requested_operations = {item.value for item in request.authorized_operations}
            if not requested_operations.issubset(context.authorized_operations):
                return _block(
                    GuardrailStage.ACTION,
                    "DOMAIN_OPERATION_NOT_AUTHORIZED",
                    "ACTION-AUTH-002",
                    "领域请求包含本轮未授权的操作",
                )
            deep_code = action_rejects_unauthorized_deep(
                objective=request.objective,
                success_criteria=list(request.success_criteria),
                authorized_capabilities=context.authorized_capabilities,
            )
            if deep_code:
                return _block(
                    GuardrailStage.ACTION,
                    deep_code,
                    "ACTION-RESEARCH-DEEP-001",
                    "深度研究未在本轮授权能力内，禁止调用",
                )
        return _allow(GuardrailStage.ACTION)


class DefaultDataQualityGuardrail:
    def evaluate_data_quality(
        self, observation: Any, *, context: GuardrailContext
    ) -> GuardrailResult[Any]:
        del context
        data = observation.model_dump(mode="json") if hasattr(observation, "model_dump") else observation
        if not isinstance(data, dict):
            return _block(
                GuardrailStage.DATA_QUALITY,
                "DATA_CONTRACT_INVALID",
                "DATA-CONTRACT-001",
                "数据结果不符合结构化契约",
            )
        if str(data.get("status", "SUCCESS")) in {"FAILED", "UNAVAILABLE"}:
            errors = data.get("errors")
            first_error = errors[0] if isinstance(errors, list) and errors else None
            error_code = first_error.get("code") if isinstance(first_error, dict) else None
            error_message = first_error.get("message") if isinstance(first_error, dict) else None
            if error_code is None and data.get("error_code"):
                error_code = data.get("error_code")
                error_message = data.get("error_message")
            return _block(
                GuardrailStage.DATA_QUALITY,
                str(error_code or "DATA_UNAVAILABLE"),
                "DATA-STATUS-001",
                str(error_message or "所需数据当前不可用"),
            )
        authenticity = _values_for_key(data, "data_mode") | _values_for_key(data, "source_type")
        if authenticity & {"MOCK", "TEST_FIXTURE"}:
            return _block(
                GuardrailStage.DATA_QUALITY,
                "NON_PRODUCTION_DATA",
                "DATA-AUTHENTICITY-001",
                "测试或模拟数据不能支撑真实结论",
            )
        confidence = data.get("confidence")
        coverage = confidence.get("coverage_status") if isinstance(confidence, dict) else None
        if str(data.get("status")) == "COMPLETE" and coverage in {"PARTIAL", "LIMITED"}:
            return _block(
                GuardrailStage.DATA_QUALITY,
                "COVERAGE_STATUS_CONFLICT",
                "DATA-COVERAGE-001",
                "领域状态与覆盖率不一致，不能升格为完整结论",
            )
        research_hit = evaluate_research_observation(data)
        if research_hit is not None:
            code, rule_id, reason = research_hit
            return _block(GuardrailStage.DATA_QUALITY, code, rule_id, reason)
        return _allow(GuardrailStage.DATA_QUALITY)


class DefaultResponseGuardrail:
    _TRADING_TERMS = (
        "立即买入", "立即卖出", "下单", "调仓", "保证收益", "稳赚", "guaranteed return",
    )
    _ACCOUNT_LEAK_TERMS = ("完整账户明细", "其他用户持仓", "其他用户账户")

    def evaluate_response(
        self, response: PublicResponse, *, context: GuardrailContext
    ) -> GuardrailResult[PublicResponse]:
        del context
        scanned_text = "\n".join(
            [
                response.message,
                *[item.title for item in response.sections],
                *[entry for item in response.sections for entry in item.items],
                *response.risk_disclosures,
                *response.next_steps,
                *response.limitations,
            ]
        )
        if any(term in scanned_text for term in self._TRADING_TERMS):
            return _block(
                GuardrailStage.RESPONSE,
                "TRADING_SEMANTICS_BLOCKED",
                "RESPONSE-READ-ONLY-001",
                "回复包含被禁止的交易或收益承诺语义",
            )
        if any(term in scanned_text for term in self._ACCOUNT_LEAK_TERMS):
            return _block(
                GuardrailStage.RESPONSE,
                "ACCOUNT_DISCLOSURE_BLOCKED",
                "RESPONSE-PRIVACY-001",
                "回复包含被禁止的账户披露语义",
            )
        research_hit = evaluate_research_response_text(scanned_text)
        if research_hit is not None:
            code, rule_id, reason = research_hit
            return _block(GuardrailStage.RESPONSE, code, rule_id, reason)
        if response.response_kind == "DOMAIN_RESULT" and not response.evidence_refs:
            return _block(
                GuardrailStage.RESPONSE,
                "EVIDENCE_REQUIRED",
                "RESPONSE-EVIDENCE-001",
                "领域结论必须携带可追溯证据",
            )
        evidence_sections = {"FACTS", "FINDINGS"}
        if (
            response.response_kind == "LIMITED"
            and any(item.section_type in evidence_sections for item in response.sections)
            and not response.evidence_refs
        ):
            return _block(
                GuardrailStage.RESPONSE,
                "EVIDENCE_REQUIRED",
                "RESPONSE-EVIDENCE-002",
                "受限领域结论仍必须携带可追溯证据",
            )
        if response.response_kind == "ASK_USER" and not response.next_steps:
            return _modify(
                response,
                response.model_copy(update={"next_steps": ["请补充问题中要求的信息后继续。"]}),
                "ASK_USER_NEXT_STEP_ADDED",
                "RESPONSE-ASK-001",
                "追问回复已补充用户可执行的下一步",
            )
        if response.response_kind == "DOMAIN_RESULT" and response.limitations:
            replacement = response.model_copy(update={"response_kind": "LIMITED"})
            return GuardrailResult(
                stage=GuardrailStage.RESPONSE,
                decision=GuardrailDecision.MODIFY,
                replacement=replacement,
                audit_code="LIMITATIONS_PROPAGATED",
                rule_ids=["RESPONSE-LIMITATION-002"],
                reasons=["领域限制已传递到公开响应"],
            )
        if response.response_kind == "LIMITED" and not response.limitations:
            return _block(
                GuardrailStage.RESPONSE,
                "LIMITATION_DISCLOSURE_REQUIRED",
                "RESPONSE-LIMITATION-001",
                "受限结果必须披露限制",
            )
        return _allow(GuardrailStage.RESPONSE)


def _allow(stage: GuardrailStage) -> GuardrailResult[Any]:
    return GuardrailResult(stage=stage, decision=GuardrailDecision.ALLOW)


def _block(
    stage: GuardrailStage, code: str, rule_id: str, reason: str
) -> GuardrailResult[Any]:
    return GuardrailResult(
        stage=stage,
        decision=GuardrailDecision.BLOCK,
        audit_code=code,
        rule_ids=[rule_id],
        reasons=[reason],
    )


def _modify(
    original: PublicResponse,
    replacement: PublicResponse,
    code: str,
    rule_id: str,
    reason: str,
) -> GuardrailResult[PublicResponse]:
    del original
    return GuardrailResult(
        stage=GuardrailStage.RESPONSE,
        decision=GuardrailDecision.MODIFY,
        replacement=replacement,
        audit_code=code,
        rule_ids=[rule_id],
        reasons=[reason],
    )


def _values_for_key(value: Any, key: str) -> set[str]:
    """递归读取真实性标记，不依赖任何具体领域模型。"""
    found: set[str] = set()
    if isinstance(value, dict):
        for item_key, item_value in value.items():
            if item_key == key and item_value is not None:
                found.add(str(item_value))
            found.update(_values_for_key(item_value, key))
    elif isinstance(value, list):
        for item in value:
            found.update(_values_for_key(item, key))
    return found
