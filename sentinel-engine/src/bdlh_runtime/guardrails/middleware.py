"""治理中间件（设计文档 §4.4、WO-T2-2）。

工具调用的唯一执行咽喉：本地工具与 MCP 工具走同一条拦截链，新增工具
无需治理侧适配。目录经 Protocol 读取（本包不 import ``tools``，满足内核纯净度）。

拦截顺序固定：G1 可见性 → G2 只读 → G3 权限 → G4 预算 → G5 参数校验
→ 执行 → G6 Observation 包装 → G7 审计记录。任一前置拦截即终止并返回
结构化拒绝（含审计码）。
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from pydantic import BaseModel

from bdlh_runtime.contracts.observation import DataQuality, Observation, ProvenanceRecord

from .contracts import GuardrailContext, GuardrailDecision, GuardrailResult, GuardrailStage
from .policies import DefaultDataQualityGuardrail

ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[Any]]

#: premium 工具按 cost_hint 加权扣减（§4.3 G-γ）；free/normal 计 1。
_COST_WEIGHT = {"free": 1, "normal": 1, "premium": 3}

_AUDIT_TOOL_NOT_VISIBLE = "TOOL_NOT_VISIBLE"
_AUDIT_READ_ONLY_REQUIRED = "READ_ONLY_REQUIRED"
_AUDIT_AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
_AUDIT_SCOPE_DENIED = "SCOPE_DENIED"
_AUDIT_BUDGET_EXCEEDED = "TOOL_BUDGET_EXCEEDED"
_AUDIT_ARGUMENTS_INVALID = "ARGUMENTS_INVALID"
_AUDIT_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"


@runtime_checkable
class ToolDescriptor(Protocol):
    """ToolCard 只读视图（七字段中治理所需部分）。"""

    name: str
    read_only: bool
    required_scope: list[str]
    cost_hint: object
    parameters: dict[str, Any]
    origin: object


@runtime_checkable
class ToolLookup(Protocol):
    """工具目录读取面。``ToolCatalog`` 满足本协议，中间件不维护第二份清单。"""

    def get(self, name: str) -> ToolDescriptor: ...

    def contains(self, name: str) -> bool: ...


class AuditRecord(BaseModel):
    """G7 审计记录（设计文档 §4.4）。"""

    caller: str
    tool_name: str
    arguments_summary: str
    elapsed_ms: int
    status: str
    audit_code: str | None = None


class MiddlewareResult(BaseModel):
    """一次 ``invoke`` 的结构化结果：放行则带 Observation，拦截则带拒绝。"""

    observation: Observation | None = None
    rejection: GuardrailResult | None = None
    audit: AuditRecord

    @property
    def allowed(self) -> bool:
        return self.rejection is None and self.observation is not None


class GovernanceMiddleware:
    """G1–G7 拦截链。每个运行实例持有一份预算余额。"""

    def __init__(
        self,
        catalog: ToolLookup,
        *,
        context: GuardrailContext,
        data_quality: DefaultDataQualityGuardrail | None = None,
    ) -> None:
        self._catalog = catalog
        self._context = context
        self._data_quality = data_quality or DefaultDataQualityGuardrail()
        self._remaining = context.max_tool_calls
        self._audits: list[AuditRecord] = []

    @property
    def remaining_budget(self) -> int:
        return self._remaining

    @property
    def audits(self) -> list[AuditRecord]:
        return list(self._audits)

    async def invoke(
        self,
        *,
        name: str,
        arguments: Mapping[str, Any] | None,
        loaded_names: Iterable[str],
        granted_scopes: Iterable[str],
        authenticated: bool,
        executor: ToolExecutor,
    ) -> MiddlewareResult:
        """执行一条工具调用。G1–G5 拒绝时不调用 ``executor``。"""
        started = time.monotonic()
        args = dict(arguments or {})
        loaded = frozenset(loaded_names)
        scopes = frozenset(granted_scopes)

        blocked = self._pre_gates(name, args, loaded, scopes, authenticated)
        if blocked is not None:
            return self._finish(
                name,
                args,
                started,
                status="REJECTED",
                rejection=blocked,
            )

        weight = _weight_for(self._catalog.get(name))
        self._remaining -= weight

        try:
            raw = await executor(name, args)
        except Exception as exc:  # noqa: BLE001 —— 咽喉必须结构化收口，禁止异常漏出
            elapsed_ms = _elapsed_ms(started)
            failed = _failed_observation(name, str(exc), elapsed_ms)
            return self._finish(
                name,
                args,
                started,
                status="FAILED",
                observation=failed,
                rejection=_block(
                    GuardrailStage.ACTION,
                    _AUDIT_EXECUTION_FAILED,
                    "TOOL-EXEC-001",
                    "工具执行失败",
                ),
                elapsed_ms=elapsed_ms,
            )

        elapsed_ms = _elapsed_ms(started)
        observation = _wrap_observation(name, raw, elapsed_ms, self._catalog.get(name))
        quality = self._data_quality.evaluate_data_quality(observation, context=self._context)
        if quality.decision != GuardrailDecision.ALLOW:
            return self._finish(
                name,
                args,
                started,
                status="REJECTED",
                observation=observation,
                rejection=quality,
                elapsed_ms=elapsed_ms,
            )
        return self._finish(
            name,
            args,
            started,
            status="SUCCESS",
            observation=observation,
            elapsed_ms=elapsed_ms,
        )

    def _pre_gates(
        self,
        name: str,
        arguments: dict[str, Any],
        loaded: frozenset[str],
        scopes: frozenset[str],
        authenticated: bool,
    ) -> GuardrailResult | None:
        if name not in loaded or not self._catalog.contains(name):
            return _block(
                GuardrailStage.ACTION,
                _AUDIT_TOOL_NOT_VISIBLE,
                "G1-VISIBLE-001",
                "工具名不在当次装载集合（防幻觉）",
            )
        card = self._catalog.get(name)
        if not self._context.read_only or not bool(card.read_only):
            return _block(
                GuardrailStage.ACTION,
                _AUDIT_READ_ONLY_REQUIRED,
                "G2-READONLY-001",
                "只读红线：禁止调用非只读工具",
            )
        required = list(card.required_scope or [])
        if "authenticated" in required and not authenticated:
            return _block(
                GuardrailStage.ACTION,
                _AUDIT_AUTHENTICATION_REQUIRED,
                "G3-AUTH-001",
                "该工具仅机主可调用",
            )
        if required and not scopes.intersection(required):
            return _block(
                GuardrailStage.ACTION,
                _AUDIT_SCOPE_DENIED,
                "G3-SCOPE-001",
                "当前身份 / 场景无权调用该工具",
            )
        weight = _weight_for(card)
        if self._remaining < weight:
            return _block(
                GuardrailStage.ACTION,
                _AUDIT_BUDGET_EXCEEDED,
                "G4-BUDGET-001",
                "本轮工具调用预算已耗尽",
            )
        schema_error = _validate_arguments(card.parameters, arguments)
        if schema_error is not None:
            return _block(
                GuardrailStage.ACTION,
                _AUDIT_ARGUMENTS_INVALID,
                "G5-SCHEMA-001",
                schema_error,
            )
        return None

    def _finish(
        self,
        name: str,
        arguments: dict[str, Any],
        started: float,
        *,
        status: str,
        observation: Observation | None = None,
        rejection: GuardrailResult | None = None,
        elapsed_ms: int | None = None,
    ) -> MiddlewareResult:
        audit = AuditRecord(
            caller=self._context.authenticated_user_id,
            tool_name=name,
            arguments_summary=_summarize_arguments(arguments),
            elapsed_ms=_elapsed_ms(started) if elapsed_ms is None else elapsed_ms,
            status=status,
            audit_code=rejection.audit_code if rejection is not None else None,
        )
        self._audits.append(audit)
        return MiddlewareResult(observation=observation, rejection=rejection, audit=audit)


def _weight_for(card: ToolDescriptor) -> int:
    hint = str(getattr(card, "cost_hint", "normal")).lower()
    return _COST_WEIGHT.get(hint, 1)


def _validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> str | None:
    if not isinstance(schema, dict) or not schema:
        schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    try:
        Draft202012Validator(schema).validate(arguments)
    except SchemaError:
        return "工具参数 schema 非法"
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.path) or "(root)"
        return f"参数校验失败：{path} {exc.message}"
    return None


def _wrap_observation(name: str, raw: Any, elapsed_ms: int, card: ToolDescriptor) -> Observation:
    origin = str(getattr(card, "origin", "local") or "local")
    retrieved_at = datetime.now(UTC).isoformat()
    if isinstance(raw, Observation):
        provenance = list(raw.provenance)
        if not provenance:
            provenance = [
                ProvenanceRecord(
                    source=origin,
                    tool=name,
                    retrieved_at=retrieved_at,
                    elapsed_ms=elapsed_ms,
                )
            ]
        elif provenance[0].elapsed_ms is None:
            provenance[0] = provenance[0].model_copy(update={"elapsed_ms": elapsed_ms})
        update: dict[str, Any] = {"provenance": provenance}
        lifted_type, lifted_payload = _lift_typed_result(raw.data, raw.result_type, raw.payload)
        if lifted_type and not raw.result_type:
            update["result_type"] = lifted_type
        if lifted_payload is not None and raw.payload is None:
            update["payload"] = lifted_payload
        return raw.model_copy(update=update)
    data = raw if isinstance(raw, dict) else {"value": raw}
    result_type, payload = _lift_typed_result(data, None, None)
    return Observation(
        observation_id=str(uuid4()),
        capability=name,
        status="SUCCESS",
        data=data,
        data_quality=DataQuality(completeness=1.0, quality_status="OK"),
        provenance=[
            ProvenanceRecord(
                source=origin,
                tool=name,
                retrieved_at=retrieved_at,
                elapsed_ms=elapsed_ms,
            )
        ],
        result_type=result_type,
        payload=payload,
    )


def _lift_typed_result(
    data: Any,
    result_type: str | None,
    payload: dict[str, Any] | None,
) -> tuple[str | None, dict[str, Any] | None]:
    if isinstance(data, dict):
        if not result_type:
            raw_type = data.get("result_type")
            if isinstance(raw_type, str) and raw_type.strip():
                result_type = raw_type.strip()
        if payload is None:
            raw_payload = data.get("payload")
            if isinstance(raw_payload, dict):
                payload = raw_payload
    return result_type, payload


def _failed_observation(name: str, message: str, elapsed_ms: int) -> Observation:
    return Observation(
        observation_id=str(uuid4()),
        capability=name,
        status="FAILED",
        data=None,
        data_quality=DataQuality(quality_status="INVALID"),
        provenance=[
            ProvenanceRecord(
                source="local",
                tool=name,
                retrieved_at=datetime.now(UTC).isoformat(),
                elapsed_ms=elapsed_ms,
            )
        ],
        error_code=_AUDIT_EXECUTION_FAILED,
        error_message=message,
    )


def _summarize_arguments(arguments: dict[str, Any]) -> str:
    raw = json.dumps(arguments, ensure_ascii=False, default=str, sort_keys=True)
    if len(raw) > 240:
        return raw[:237] + "..."
    return raw


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _block(stage: GuardrailStage, code: str, rule_id: str, reason: str) -> GuardrailResult:
    return GuardrailResult(
        stage=stage,
        decision=GuardrailDecision.BLOCK,
        audit_code=code,
        rule_ids=[rule_id],
        reasons=[reason],
    )
