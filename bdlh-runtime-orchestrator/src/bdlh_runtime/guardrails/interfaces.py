"""M4 四时点 Guardrail 接口。

四个 Protocol 有意分开定义。策略可以独立替换，但不得将它们合并
成一个无法区分计划、动作、数据质量和回复责任的万能检查器。
"""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from .contracts import GuardrailContext, GuardrailResult

PlanT = TypeVar("PlanT", contravariant=True)
PlanReplacementT = TypeVar("PlanReplacementT")
ActionT = TypeVar("ActionT", contravariant=True)
ActionReplacementT = TypeVar("ActionReplacementT")
ObservationT = TypeVar("ObservationT", contravariant=True)
ObservationReplacementT = TypeVar("ObservationReplacementT")
ResponseT = TypeVar("ResponseT", contravariant=True)
ResponseReplacementT = TypeVar("ResponseReplacementT")


@runtime_checkable
class PlanGuardrail(Protocol[PlanT, PlanReplacementT]):
    """计划生成后检查：目标、能力注册、预算和只读边界。"""

    def evaluate_plan(
        self,
        plan: PlanT,
        *,
        context: GuardrailContext,
    ) -> GuardrailResult[PlanReplacementT]: ...


@runtime_checkable
class ActionGuardrail(Protocol[ActionT, ActionReplacementT]):
    """工具/领域动作执行前检查：权限、白名单、参数和副作用。"""

    def evaluate_action(
        self,
        action: ActionT,
        *,
        context: GuardrailContext,
    ) -> GuardrailResult[ActionReplacementT]: ...


@runtime_checkable
class DataQualityGuardrail(Protocol[ObservationT, ObservationReplacementT]):
    """Observation 标准化后检查：错误、时效、覆盖率和来源冲突。"""

    def evaluate_data_quality(
        self,
        observation: ObservationT,
        *,
        context: GuardrailContext,
    ) -> GuardrailResult[ObservationReplacementT]: ...


@runtime_checkable
class ResponseGuardrail(Protocol[ResponseT, ResponseReplacementT]):
    """最终回复生成后检查：事实引用、限制、只读与风险表达。"""

    def evaluate_response(
        self,
        response: ResponseT,
        *,
        context: GuardrailContext,
    ) -> GuardrailResult[ResponseReplacementT]: ...
