"""统一运行遥测:运行事件、逐步明细与九段统一工件(开发计划 §4.3、评测文档 §9)。

执行器(统一原生 Tool Calling 底座)同口径产出 ``RunRecord``:
- 事件流(``run_events``;含 model.requested / model.result_appended 逐轮锚点,
  见 docs/design/Agent运行链路可观测性优化设计.md §6.3);
- 每次模型调用(``model_calls`` + ``model_call_messages``;含当轮 Tool Schema
  与 requested/sent/unsupported 参数三态快照)与每次工具执行
  (``tool_calls``;关联发起模型调用、模型 call_id 与全局事件序号);
- guardrail 检查明细(``guardrail_checks``)与分阶段测量(``run_measurements``);
- 九段统一工件(``run_artifacts`` + ARTIFACTS_DIR 文件双写,hash 可复算)。

有效性分类(架构文档 §7.1):429 / 余额不足 / 模型服务不可用 / 工件写失败 →
INVALID(不进能力统计);有效环境下的任务失败 → FAILED(作为失败样本计数)。
落库经 data 服务 internal 接口,engine 不直连库。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable

from bdlh_runtime.context import (
    CONSERVATIVE_TOKENIZER_VERSION,
    ConservativeTokenCounter,
    ContextAction,
    ContextBuildResult,
    ContextItem,
)

# ── 事件类型(开发计划 §4.3 九类 + 可观测性设计 §6.3 增补两类)──────────────

EVENT_RUN_STARTED = "run.started"
EVENT_CONTEXT_COMPLETED = "context.completed"
EVENT_MODEL_REQUESTED = "model.requested"
EVENT_MODEL_COMPLETED = "model.completed"
EVENT_TOOL_REQUESTED = "tool.requested"
EVENT_TOOL_COMPLETED = "tool.completed"
EVENT_MODEL_RESULT_APPENDED = "model.result_appended"
EVENT_GUARDRAIL_COMPLETED = "guardrail.completed"
EVENT_OUTPUT_COMPLETED = "output.completed"
EVENT_JUDGMENT_COMPLETED = "judgment.completed"
EVENT_RUN_COMPLETED = "run.completed"

RUN_EVENT_TYPES = frozenset(
    {
        EVENT_RUN_STARTED,
        EVENT_CONTEXT_COMPLETED,
        EVENT_MODEL_REQUESTED,
        EVENT_MODEL_COMPLETED,
        EVENT_TOOL_REQUESTED,
        EVENT_TOOL_COMPLETED,
        EVENT_MODEL_RESULT_APPENDED,
        EVENT_GUARDRAIL_COMPLETED,
        EVENT_OUTPUT_COMPLETED,
        EVENT_JUDGMENT_COMPLETED,
        EVENT_RUN_COMPLETED,
    }
)

# ── 运行状态与有效性(架构文档 §7.1)───────────────────────────────────────

RUN_STATUS_COMPLETE = "COMPLETE"
RUN_STATUS_FAILED = "FAILED"
RUN_STATUS_INVALID = "INVALID"
RUN_STATUS_CANCELLED = "CANCELLED"

VALIDITY_VALID = "VALID"
VALIDITY_INVALID = "INVALID"

#: agent_mode 值(与 agent_runs.agent_mode 一致):统一原生 Tool Calling 底座。
MODE_NATIVE = "native-tool-calling"

# token 口径:model_call_messages 粗估用 chars//4;上下文构建用
# ConservativeTokenCounter(版本见 context.token_count,工件 provenance 记录)
TOKENIZER_VERSION = "conservative-chars4-v1"

_RATE_LIMIT_MARKERS = ("429", "rate limit", "ratelimit", "too many requests", "请求过于频繁", "频率限制")
_BALANCE_MARKERS = (
    "余额不足",
    "insufficient balance",
    "balance is insufficient",
    "insufficient_balance",
    "欠费",
    "arrears",
    # provider 实测文案:Error code: 402 - {'code': 30001, 'message': 'Sorry, your account balance is insufficient'}
    "error code: 402",
    "30001",
)
_UNAVAILABLE_MARKERS = (
    "connection",
    "connect",
    "timeout",
    "timed out",
    "超时",
    "unreachable",
    "refused",
    "reset by peer",
    "502",
    "503",
    "504",
    "unauthorized",
    "401",
    "403",
    "api key",
    "model not found",
    "service unavailable",
)
#: 上下文构建失败(强制项超预算等)按评测环境错误处理,不算 Agent 失败样本
_CONTEXT_BUILD_MARKERS = ("required context needs", "working context needs")


def classify_failure(error: str | None) -> tuple[str, str]:
    """按错误文本分类 → (run_status, error_category)。

    无错误返回 (COMPLETE, "");基础设施/环境类错误(429/余额/服务不可用/上下文
    构建失败)→ INVALID,不进能力统计;其余为有效环境下的任务失败 → FAILED。
    """

    if not error:
        return RUN_STATUS_COMPLETE, ""
    text = str(error).lower()
    if any(marker in text for marker in _RATE_LIMIT_MARKERS):
        return RUN_STATUS_INVALID, "RATE_LIMITED"
    if any(marker in text for marker in _BALANCE_MARKERS):
        return RUN_STATUS_INVALID, "INSUFFICIENT_BALANCE"
    if any(marker in text for marker in _CONTEXT_BUILD_MARKERS):
        return RUN_STATUS_INVALID, "CONTEXT_BUILD_FAILED"
    if any(marker in text for marker in _UNAVAILABLE_MARKERS):
        return RUN_STATUS_INVALID, "MODEL_SERVICE_UNAVAILABLE"
    return RUN_STATUS_FAILED, "AGENT_ERROR"


def validity_of(status: str) -> str:
    return VALIDITY_INVALID if status == RUN_STATUS_INVALID else VALIDITY_VALID


# ── hash 与 token 口径 ───────────────────────────────────────────────────


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def payload_hash(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


#: 请求快照协议版本(request_payload/tool_schemas/参数列的联合协议号)
REQUEST_SNAPSHOT_VERSION = 1


def request_fingerprint(
    *,
    model: str,
    messages: list[dict[str, Any]],
    tool_schemas: list[Any] | None = None,
    sent_params: dict[str, Any] | None = None,
) -> str:
    """请求指纹:覆盖 model + 规范化 messages + 当轮 tool_schemas + sent 参数。

    不能只覆盖消息——工具提供方式或模型参数改变后哈希必须变化
    (可观测性设计 §4.3);规范化走 canonical_json(键排序 + 紧凑分隔)。
    """
    return payload_hash(
        {
            "model": model,
            "messages": messages,
            "toolSchemas": list(tool_schemas or []),
            "sentParams": dict(sent_params or {}),
        }
    )


def estimate_tokens(text: str | None) -> int:
    """保守字符估算(chars//4);与 ``TOKENIZER_VERSION`` 口径绑定。"""
    return max(0, len(text or "") // 4)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


# ── 明细行 ───────────────────────────────────────────────────────────────


@dataclass
class ModelCallRow:
    """一次模型请求:model_calls 行 + 输入消息快照(model_call_messages)。

    快照字段(可观测性设计 §4.3/§6.1):tool_schemas 为当轮实际绑定内容
    (search 提供方式下逐轮不同);参数三态 requested/sent/unsupported 在
    模型客户端构建完成后确定、逐调用盖章;request_hash 由 request_fingerprint
    覆盖 model+messages+tool_schemas+sent 参数,不只覆盖消息。
    """

    sequence: int
    model: str = ""
    purpose: str = "AGENT"
    request_hash: str = ""
    response_hash: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    tokens_estimated: bool = False
    duration_ms: int = 0
    retry_count: int = 0
    status: str = "COMPLETE"  # COMPLETE / FAILED / INVALID
    error_category: str | None = None
    decision: str = "answer"  # call_tool / answer
    tools: list[str] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    request_snapshot_version: int = REQUEST_SNAPSHOT_VERSION
    tool_schemas: list[dict[str, Any]] = field(default_factory=list)
    requested_params: dict[str, Any] = field(default_factory=dict)
    sent_params: dict[str, Any] = field(default_factory=dict)
    unsupported_params: dict[str, Any] = field(default_factory=dict)
    response_summary: dict[str, Any] = field(default_factory=dict)
    _t: float = 0.0

    def to_payload(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "purpose": self.purpose,
            "model": self.model,
            "requestHash": self.request_hash,
            "responseHash": self.response_hash,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "durationMs": self.duration_ms,
            "retryCount": self.retry_count,
            "status": self.status,
            "errorCategory": self.error_category,
            "decision": self.decision,
            "requestSnapshotVersion": self.request_snapshot_version,
            "toolSchemas": self.tool_schemas,
            "requestedParams": self.requested_params,
            "sentParams": self.sent_params,
            "unsupportedParams": self.unsupported_params,
            "responseSummary": self.response_summary,
            "messages": self.messages,
        }


@dataclass
class ToolCallRow:
    """一次工具执行请求:成功/失败按执行结果,被治理拦截记 DENIED。

    调用关联(可观测性设计 §4.4/§6.2):model_call_sequence 指向发起本次
    执行的模型调用,call_id 为模型生成的调用 id(与 ToolMessage.tool_call_id
    对应),requested/completed_event_sequence 指向 run_events 全局序号,
    三者共同重建「模型 → 工具 → 模型」真实顺序。
    """

    sequence: int
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    arguments_hash: str = ""
    status: str = "SUCCESS"  # SUCCESS / FAILED / TIMEOUT / DENIED / INVALID
    result_summary: dict[str, Any] = field(default_factory=dict)
    result_hash: str | None = None
    source_time: str | None = None
    duration_ms: int = 0
    audit_code: str | None = None
    fixture_hit: bool = True
    error_category: str | None = None
    model_call_sequence: int | None = None
    call_id: str | None = None
    requested_event_sequence: int | None = None
    completed_event_sequence: int | None = None
    _t: float = 0.0

    def to_payload(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "toolName": self.tool_name,
            "arguments": self.arguments,
            "argumentsHash": self.arguments_hash,
            "status": self.status,
            "resultSummary": self.result_summary,
            "resultHash": self.result_hash,
            "sourceTime": self.source_time,
            "durationMs": self.duration_ms,
            "auditCode": self.audit_code,
            "fixtureHit": self.fixture_hit,
            "errorCategory": self.error_category,
            "modelCallSequence": self.model_call_sequence,
            "callId": self.call_id,
            "requestedEventSequence": self.requested_event_sequence,
            "completedEventSequence": self.completed_event_sequence,
        }


@dataclass
class GuardrailCheckRow:
    """一次治理检查:四时点(plan/action/data_quality/response)。"""

    sequence: int
    stage: str
    decision: str  # allow / block / modify / ask_user
    audit_code: str | None = None
    rule_ids: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    tool_name: str | None = None
    tool_call_sequence: int | None = None
    model_call_sequence: int | None = None
    duration_ms: int = 0
    detail: dict[str, Any] = field(default_factory=dict)
    _t: float = 0.0

    def to_payload(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "stage": self.stage,
            "decision": self.decision,
            "auditCode": self.audit_code,
            "ruleIds": self.rule_ids,
            "reasons": self.reasons,
            "toolName": self.tool_name,
            "toolCallSequence": self.tool_call_sequence,
            "modelCallSequence": self.model_call_sequence,
            "durationMs": self.duration_ms,
            "detail": self.detail,
        }


@dataclass
class RunRecord:
    """一次运行(case × agent_mode × repeat)的全部可观察过程。"""

    run_key: str
    case_id: str
    case_version: int
    variant_id: str
    snapshot_id: str
    snapshot_hash: str
    agent_mode: str
    context_strategy: str
    model: str
    repeat_index: int
    message: str
    category: str
    # 发布投影所需(任务五):场景/登录态/历史轮数/当次可见工具
    scene: str = ""
    authenticated: bool = False
    history_turns: int = 0
    visible_tools: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    model_calls: list[ModelCallRow] = field(default_factory=list)
    tool_calls: list[ToolCallRow] = field(default_factory=list)
    guardrail_checks: list[GuardrailCheckRow] = field(default_factory=list)
    measurements: dict[str, Any] = field(default_factory=dict)
    judgment: dict[str, Any] = field(default_factory=dict)
    answer_excerpt: str = ""
    run_id: str | None = None
    batch_id: str | None = None
    started_at: str = ""
    completed_at: str | None = None
    duration_ms: int = 0
    status: str = RUN_STATUS_COMPLETE
    error_category: str | None = None
    error_text: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    #: 上下文构建报告(context_builds 落库载荷;未走构建器的组保持 None)
    context_build: dict[str, Any] | None = None


# ── RunRecorder:事件总线 + 明细收集 ──────────────────────────────────────


class RunRecorder:
    """per-run 遥测收集器:批内内存收集,批后经 data 服务统一落库。"""

    def __init__(
        self,
        *,
        run_key: str,
        case_id: str,
        case_version: int,
        variant_id: str,
        snapshot_id: str,
        snapshot_hash: str,
        agent_mode: str,
        context_strategy: str,
        model: str,
        repeat_index: int,
        message: str,
        category: str,
        scene: str = "",
        authenticated: bool = False,
        history_turns: int = 0,
    ) -> None:
        self.record = RunRecord(
            run_key=run_key,
            case_id=case_id,
            case_version=case_version,
            variant_id=variant_id,
            snapshot_id=snapshot_id,
            snapshot_hash=snapshot_hash,
            agent_mode=agent_mode,
            context_strategy=context_strategy,
            model=model,
            repeat_index=repeat_index,
            message=message,
            category=category,
            scene=scene,
            authenticated=authenticated,
            history_turns=history_turns,
            started_at=_now_iso(),
            status=RUN_STATUS_COMPLETE,
        )
        self._event_seq = 0
        self._model_seq = 0
        self._tool_seq = 0
        self._guard_seq = 0
        self._started = time.perf_counter()
        self._judgment_started = 0.0
        # 事件监听器(阶段二实时通道:发布器订阅 emit,异常不影响执行)
        self._event_listeners: list[Any] = []
        # 请求参数三态(模型客户端构建完成后 attach;逐模型调用盖章)
        self._model_params: dict[str, dict[str, Any]] = {"requested": {}, "sent": {}, "unsupported": {}}
        # 待配对的模型生成 call_id(按名称 FIFO;工具执行与治理拦截各按序消费)
        self._pending_tool_calls: list[dict[str, str | None]] = []
        self._last_model_sequence: int | None = None
        self.emit(
            EVENT_RUN_STARTED,
            {
                "caseId": case_id,
                "caseVersion": case_version,
                "variantId": variant_id,
                "snapshotId": snapshot_id,
                "agentMode": agent_mode,
                "model": model,
                "repeatIndex": repeat_index,
            },
        )

    @classmethod
    def for_template_run(
        cls,
        *,
        run_id: str,
        model: str,
        variant_label: str = "",
        repeat_index: int = 0,
        message: str = "",
        context_strategy: str = "full",
        config_hash: str = "",
        template_id: str = "",
    ) -> RunRecorder:
        """正式模板/实验组运行的 per-run recorder(与 eval 链路同一落库协议)。

        RunRecord 的 case 维度字段按模板语义填充(case_id=template_id、
        snapshot 取配置哈希口径);agent_runs 行仍由 run_api 按注册用例另行
        创建,本 recorder 只负责事件与明细收集,保证正式模板与评测链路
        产出同构的 events/model_calls/tool_calls/guardrail_checks。
        """
        return cls(
            run_key=run_id,
            case_id=template_id or "template",
            case_version=1,
            variant_id=variant_label or "default",
            snapshot_id=f"template:{config_hash[:12]}" if config_hash else "template",
            snapshot_hash=config_hash,
            agent_mode=MODE_NATIVE,
            context_strategy=context_strategy,
            model=model,
            repeat_index=repeat_index,
            message=message,
            category="TEMPLATE",
        )

    # -- 事件 ---------------------------------------------------------------

    def add_event_listener(self, listener: Any) -> None:
        """订阅事件流(实时发布器用);监听器异常被抑制,绝不影响执行。"""
        self._event_listeners.append(listener)

    def emit(self, event_type: str, payload: dict[str, Any]) -> int:
        if event_type not in RUN_EVENT_TYPES:
            raise ValueError(f"unknown run event type: {event_type}")
        self._event_seq += 1
        event = {
            "sequence": self._event_seq,
            "eventType": event_type,
            "payload": payload,
            "occurredAt": _now_iso(),
        }
        self.record.events.append(event)
        for listener in tuple(self._event_listeners):
            try:
                listener(event)
            except Exception as exc:  # noqa: BLE001 —— 观测旁路失败不改变执行
                print(f"[run_telemetry] 事件监听器异常(已忽略):{type(exc).__name__}: {exc}")
        return self._event_seq

    # -- 明细行 --------------------------------------------------------------

    def record_model_call(self, row: ModelCallRow) -> ModelCallRow:
        self.record.model_calls.append(row)
        self._last_model_sequence = row.sequence
        self.emit(
            EVENT_MODEL_COMPLETED,
            {
                "sequence": row.sequence,
                "decision": row.decision,
                "tools": row.tools,
                "inputTokens": row.input_tokens,
                "outputTokens": row.output_tokens,
                "durationMs": row.duration_ms,
                "status": row.status,
            },
        )
        return row

    def record_tool_call(self, row: ToolCallRow) -> ToolCallRow:
        self.record.tool_calls.append(row)
        return row

    def record_guardrail_check(self, row: GuardrailCheckRow) -> GuardrailCheckRow:
        self.record.guardrail_checks.append(row)
        self.emit(
            EVENT_GUARDRAIL_COMPLETED,
            {
                "sequence": row.sequence,
                "stage": row.stage,
                "decision": row.decision,
                "auditCode": row.audit_code,
                "toolName": row.tool_name,
            },
        )
        return row

    def next_model_sequence(self) -> int:
        self._model_seq += 1
        return self._model_seq

    def next_tool_sequence(self) -> int:
        self._tool_seq += 1
        return self._tool_seq

    def next_guard_sequence(self) -> int:
        self._guard_seq += 1
        return self._guard_seq

    # -- 请求快照与调用关联(可观测性设计 §4.1/§4.4/§5.1)────────────────────

    def attach_model_params(
        self,
        *,
        requested: dict[str, Any] | None = None,
        sent: dict[str, Any] | None = None,
        unsupported: dict[str, Any] | None = None,
    ) -> None:
        """登记参数三态快照:在模型客户端完成适配后调用(采集点 §5.1),
        之后每次模型调用盖章同一份事实——同一运行内 sent 参数不逐轮漂移。"""
        self._model_params = {
            "requested": dict(requested or {}),
            "sent": dict(sent or {}),
            "unsupported": dict(unsupported or {}),
        }

    @property
    def model_params(self) -> dict[str, dict[str, Any]]:
        return self._model_params

    @property
    def last_model_call_sequence(self) -> int | None:
        return self._last_model_sequence

    def stash_tool_call_ids(self, calls: list[dict[str, Any]]) -> None:
        """记录最近一次模型响应生成的工具调用(name/callId/发起序号)。

        发起序号在 stash 时即固定为本次模型调用——治理拦截行在循环结束后
        补录,届时不能拿「最近一次模型调用」冒充发起者。
        """
        for call in calls:
            if call.get("name"):
                self._pending_tool_calls.append(
                    {
                        "name": str(call["name"]),
                        "callId": call.get("callId"),
                        "modelCallSequence": self._last_model_sequence,
                    }
                )

    def pop_pending_tool_call(self, tool_name: str) -> dict[str, Any]:
        """按名称 FIFO 取出配对项;治理拦截行同样消费,防止队列泄漏。"""
        for index, pending in enumerate(self._pending_tool_calls):
            if pending["name"] == tool_name:
                del self._pending_tool_calls[index]
                return pending
        return {}

    # -- 阶段事件 ------------------------------------------------------------

    def record_context(self, payload: dict[str, Any]) -> None:
        """context.completed 事件:payload 描述本次上下文处理(策略/条目数/token 等)。"""
        self.emit(EVENT_CONTEXT_COMPLETED, payload)

    def attach_context_build(self, build: dict[str, Any]) -> None:
        """挂载上下文构建报告(context_builds 落库载荷 + 工件 context 段真源)。"""
        self.record.context_build = dict(build)

    def record_output(self, *, answer_excerpt: str, audit_codes: list[str] | None = None) -> None:
        self.record.answer_excerpt = answer_excerpt
        self.emit(
            EVENT_OUTPUT_COMPLETED,
            {"answerExcerpt": answer_excerpt[:200], "auditCodes": audit_codes or []},
        )

    def mark_judgment_started(self) -> None:
        self._judgment_started = time.perf_counter()

    def record_judgment(self, judgment: dict[str, Any]) -> None:
        self.record.judgment = dict(judgment)
        self.emit(EVENT_JUDGMENT_COMPLETED, judgment)

    def complete(
        self,
        *,
        status: str,
        error_category: str | None = None,
        error_text: str | None = None,
    ) -> None:
        self.record.status = status
        self.record.error_category = error_category
        self.record.error_text = error_text
        self.record.completed_at = _now_iso()
        self.record.duration_ms = round((time.perf_counter() - self._started) * 1000)
        judgment_ms = 0
        if self._judgment_started:
            judgment_ms = round((time.perf_counter() - self._judgment_started) * 1000)
        self.record.measurements = build_measurements(self.record, judgment_ms=judgment_ms)
        self.emit(
            EVENT_RUN_COMPLETED,
            {
                "status": status,
                "validity": validity_of(status),
                "errorCategory": error_category,
                "durationMs": self.record.duration_ms,
                "modelCalls": len(self.record.model_calls),
                "toolCalls": len(self.record.tool_calls),
                "guardrailChecks": len(self.record.guardrail_checks),
            },
        )


def build_measurements(record: RunRecord, *, judgment_ms: int) -> dict[str, Any]:
    """分阶段测量(架构文档 §7.1 全链路口径中当前可观察的部分)。

    ``telemetryBytes`` 为明细四类(events/model_calls/tool_calls/guardrail_checks)
    的 canonical JSON 字节总量,与 telemetry_audit.storage 同口径(设计 §9.3)。
    """

    def _bytes(items: Any) -> int:
        return len(canonical_json(list(items)).encode("utf-8"))

    build = record.context_build or {}
    return {
        "contextCollectMs": int(build.get("durationMs") or 0),
        # 压缩发生在构建内,未单独计时;compression tokens 见 context_build
        "contextCompressMs": 0,
        "llmMs": sum(row.duration_ms for row in record.model_calls),
        "toolMs": sum(row.duration_ms for row in record.tool_calls),
        "guardrailMs": sum(row.duration_ms for row in record.guardrail_checks),
        "judgmentMs": judgment_ms,
        "totalDurationMs": record.duration_ms,
        "promptTokens": sum(row.input_tokens for row in record.model_calls),
        "completionTokens": sum(row.output_tokens for row in record.model_calls),
        "telemetryBytes": (
            _bytes(record.events)
            + sum(_bytes([row.to_payload()]) for row in record.model_calls)
            + sum(_bytes([row.to_payload()]) for row in record.tool_calls)
            + sum(_bytes([row.to_payload()]) for row in record.guardrail_checks)
        ),
    }


# ── 消息序列化(model_call_messages 输入快照)────────────────────────────


def message_role(message: Any) -> str:
    if isinstance(message, SystemMessage):
        return "system"
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, ToolMessage):
        return "tool"
    if isinstance(message, HumanMessage):
        return "user"
    return "user"


def message_content(message: Any) -> str:
    """可观察文本:正文 + 工具调用(模型输出侧的决策是可观察过程,非隐藏思维)。"""

    content = getattr(message, "content", "") or ""
    if not isinstance(content, str):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        content = "".join(parts)
    calls = getattr(message, "tool_calls", None) or []
    if calls:
        rendered = [
            {
                "name": str(call.get("name") if isinstance(call, dict) else getattr(call, "name", "")),
                "args": call.get("args") if isinstance(call, dict) else getattr(call, "args", {}),
            }
            for call in calls
        ]
        content = (content + "\n" if content else "") + json.dumps(rendered, ensure_ascii=False, default=str)
    return content


def snapshot_messages(messages: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for order, message in enumerate(messages):
        content = message_content(message)
        rows.append(
            {
                "messageOrder": order,
                "role": message_role(message),
                "content": content,
                "tokens": estimate_tokens(content),
                "contentHash": payload_hash(content),
            }
        )
    return rows


def _usage_of(response: Any) -> tuple[int, int, bool]:
    """(input_tokens, output_tokens, 是否估算);与判官同口径。

    ``usage_metadata`` 在 langchain-core 中是 **dict**:早期实现误用属性
    访问导致该字段永远读不到、静默落到估算/旧字段分支;此处 dict 与
    对象两种形态都读,真实账单口径优先于估算。
    """

    def _num(source: Any, key: str) -> int:
        value = source.get(key, 0) if isinstance(source, dict) else getattr(source, key, 0)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    usage = getattr(response, "usage_metadata", None)
    if usage:
        p = _num(usage, "input_tokens")
        c = _num(usage, "output_tokens")
        if p > 0 or c > 0:
            return p, c, False
    meta = getattr(response, "response_metadata", None)
    if isinstance(meta, dict):
        token_usage = meta.get("token_usage") or meta.get("usage") or {}
        if isinstance(token_usage, dict) and token_usage:
            p = int(token_usage.get("prompt_tokens", 0) or 0)
            c = int(token_usage.get("completion_tokens", 0) or 0)
            if p > 0 or c > 0:
                return p, c, False
    text = message_content(response)
    return 0, max(1, estimate_tokens(text)), True


# ── RecordingLLM / RecordingExecutor:执行器同口径包装 ────────────────


class _RecordingBoundModel(Runnable):
    """bind_tools 结果的记录包装:ainvoke/astream/invoke 记录后透传。

    必须是 Runnable:部分编排会把 ``prompt | model`` 组合成管道,
    鸭子类型对象无法进入该管道。
    """

    def __init__(self, inner: Any, recorder: RunRecorder, model_name: str, tool_specs: list[Any] | None = None) -> None:
        super().__init__()
        self._inner = inner
        self._recorder = recorder
        self._model = model_name
        # 当轮实际绑定给模型的 Tool Schema(bind_tools 采集点,可观测性设计 §5.1)
        self._tool_specs = list(tool_specs or [])

    def invoke(self, messages: Any, config: Any = None, **kwargs: Any) -> Any:
        started = time.perf_counter()
        input_rows = snapshot_messages(list(messages))
        _emit_model_requested(self._recorder, self._model, self._tool_specs)
        try:
            response = self._inner.invoke(messages, config=config, **kwargs)
        except Exception as exc:  # noqa: BLE001 —— 异常记录后原样抛出
            _record_failed_model_call(
                self._recorder, self._model, input_rows, started, exc, tool_specs=self._tool_specs
            )
            raise
        _record_model_response(
            response,
            list(messages),
            self._recorder,
            self._model,
            started,
            input_rows=input_rows,
            tool_specs=self._tool_specs,
        )
        return response

    async def ainvoke(self, messages: Any, config: Any = None, **kwargs: Any) -> Any:
        started = time.perf_counter()
        input_rows = snapshot_messages(list(messages))
        _emit_model_requested(self._recorder, self._model, self._tool_specs)
        try:
            response = await self._inner.ainvoke(messages, config=config, **kwargs)
        except Exception as exc:  # noqa: BLE001 —— 异常记录后原样抛出,由调用方决定重试
            _record_failed_model_call(
                self._recorder, self._model, input_rows, started, exc, tool_specs=self._tool_specs
            )
            raise
        _record_model_response(
            response,
            list(messages),
            self._recorder,
            self._model,
            started,
            input_rows=input_rows,
            tool_specs=self._tool_specs,
        )
        return response

    async def astream(self, messages: Any, config: Any = None, **kwargs: Any) -> Any:
        astream = getattr(self._inner, "astream", None)
        if not callable(astream):
            # 内层无流式面(测试替身/部分客户端):回退 ainvoke,与 AgentLoop 同语义
            yield await self.ainvoke(messages, config=config, **kwargs)
            return
        started = time.perf_counter()
        input_rows = snapshot_messages(list(messages))
        _emit_model_requested(self._recorder, self._model, self._tool_specs)
        chunks: list[Any] = []
        async for chunk in astream(messages, config=config, **kwargs):
            chunks.append(chunk)
            yield chunk
        merged = chunks[0] if chunks else AIMessage(content="")
        for item in chunks[1:]:
            try:
                merged = merged + item
            except TypeError:
                merged = item
        _record_model_response(
            merged,
            list(messages),
            self._recorder,
            self._model,
            started,
            input_rows=input_rows,
            tool_specs=self._tool_specs,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class RecordingLLM(Runnable):
    """LLM 记录包装:每次模型调用记输入快照/输出/usage/耗时;异常按类别归档。

    仅覆盖 ``invoke``/``ainvoke``/``astream``/``bind_tools``,其余属性透传内层模型。
    ``bind_tools`` 同时捕获当轮 Tool Schema——search 提供方式下逐轮不同,
    必须逐模型调用保存,不以最终 ``visible_tools`` 代替历史轮次。
    """

    def __init__(self, inner: Any, recorder: RunRecorder, model_name: str) -> None:
        super().__init__()
        self._inner = inner
        self._recorder = recorder
        self._model = model_name

    def bind_tools(self, tools: Any, **kwargs: Any) -> _RecordingBoundModel:
        return _RecordingBoundModel(
            self._inner.bind_tools(tools, **kwargs), self._recorder, self._model, tool_specs=list(tools or [])
        )

    def invoke(self, messages: Any, config: Any = None, **kwargs: Any) -> Any:
        return _RecordingBoundModel(self._inner, self._recorder, self._model).invoke(messages, config=config, **kwargs)

    async def ainvoke(self, messages: Any, config: Any = None, **kwargs: Any) -> Any:
        return await _record_model_invoke(self._inner, messages, self._recorder, self._model, config, kwargs)

    async def astream(self, messages: Any, config: Any = None, **kwargs: Any) -> Any:
        async for chunk in _RecordingBoundModel(self._inner, self._recorder, self._model).astream(
            messages, config=config, **kwargs
        ):
            yield chunk

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _emit_model_requested(recorder: RunRecorder, model_name: str, tool_specs: list[Any]) -> int:
    """model.requested:请求已组装待发送(逐轮起点,可观测性设计 §6.3)。"""
    names = [spec.get("function", {}).get("name", "") for spec in tool_specs if isinstance(spec, dict)]
    return recorder.emit(
        EVENT_MODEL_REQUESTED,
        {
            "model": model_name,
            "tools": [name for name in names if name],
            "toolSchemaHash": payload_hash(tool_specs) if tool_specs else "",
        },
    )


async def _record_model_invoke(
    inner: Any,
    messages: Any,
    recorder: RunRecorder,
    model_name: str,
    config: Any,
    kwargs: dict[str, Any],
) -> Any:
    started = time.perf_counter()
    input_rows = snapshot_messages(list(messages))
    _emit_model_requested(recorder, model_name, [])
    try:
        response = await inner.ainvoke(messages, config=config, **kwargs)
    except Exception as exc:  # noqa: BLE001 —— 异常记录后原样抛出,由调用方决定重试
        _record_failed_model_call(recorder, model_name, input_rows, started, exc)
        raise
    _record_model_response(response, list(messages), recorder, model_name, started, input_rows=input_rows)
    return response


def _record_failed_model_call(
    recorder: RunRecorder,
    model_name: str,
    input_rows: list[dict[str, Any]],
    started: float,
    exc: Exception,
    *,
    tool_specs: list[Any] | None = None,
) -> None:
    duration_ms = round((time.perf_counter() - started) * 1000)
    status, category = classify_failure(str(exc))
    params = recorder.model_params
    recorder.record_model_call(
        ModelCallRow(
            sequence=recorder.next_model_sequence(),
            model=model_name,
            request_hash=request_fingerprint(
                model=model_name,
                messages=input_rows,
                tool_schemas=tool_specs,
                sent_params=params.get("sent") or {},
            ),
            duration_ms=duration_ms,
            status="INVALID" if status == RUN_STATUS_INVALID else "FAILED",
            error_category=category,
            messages=input_rows,
            tool_schemas=list(tool_specs or []),
            requested_params=params.get("requested") or {},
            sent_params=params.get("sent") or {},
            unsupported_params=params.get("unsupported") or {},
            _t=started,
        )
    )


def _tool_calls_with_ids(response: Any) -> list[dict[str, Any]]:
    """提取模型响应生成的工具调用:(name, callId, arguments)——调用关联真源。"""

    rows: list[dict[str, Any]] = []
    for call in getattr(response, "tool_calls", None) or []:
        if not call:
            continue
        name = str(call.get("name") if isinstance(call, dict) else getattr(call, "name", ""))
        call_id = str(call.get("id") if isinstance(call, dict) else getattr(call, "id", "")) or None
        args = call.get("args") if isinstance(call, dict) else getattr(call, "args", {})
        if name:
            rows.append({"name": name, "callId": call_id, "arguments": args if isinstance(args, dict) else {}})
    return rows


def _record_model_response(
    response: Any,
    messages: list[Any],
    recorder: RunRecorder,
    model_name: str,
    started: float,
    *,
    input_rows: list[dict[str, Any]] | None = None,
    duration_ms: int | None = None,
    tool_specs: list[Any] | None = None,
) -> None:
    if input_rows is None:
        input_rows = snapshot_messages(messages)
    if duration_ms is None:
        duration_ms = round((time.perf_counter() - started) * 1000)
    input_tokens, output_tokens, estimated = _usage_of(response)
    if estimated and input_tokens == 0:
        input_tokens = sum(int(row["tokens"]) for row in input_rows)
    tool_calls = _tool_calls_with_ids(response)
    tools = [call["name"] for call in tool_calls]
    params = recorder.model_params
    specs = list(tool_specs or [])
    response_text = message_content(response)
    recorder.record_model_call(
        ModelCallRow(
            sequence=recorder.next_model_sequence(),
            model=model_name,
            request_hash=request_fingerprint(
                model=model_name,
                messages=input_rows,
                tool_schemas=specs,
                sent_params=params.get("sent") or {},
            ),
            response_hash=payload_hash(response_text),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens_estimated=estimated,
            duration_ms=duration_ms,
            status="COMPLETE",
            decision="call_tool" if tools else "answer",
            tools=tools,
            messages=input_rows,
            tool_schemas=specs,
            requested_params=params.get("requested") or {},
            sent_params=params.get("sent") or {},
            unsupported_params=params.get("unsupported") or {},
            response_summary={
                "decision": "call_tool" if tools else "answer",
                "toolCalls": [
                    {"callId": call["callId"], "name": call["name"], "arguments": call["arguments"]}
                    for call in tool_calls
                ],
                "textExcerpt": response_text[:200] if response_text else "",
            },
            _t=started,
        )
    )
    recorder.stash_tool_call_ids(tool_calls)


class RecordingExecutor:
    """工具执行器记录包装:tool.requested / tool.completed + tool_calls 行。

    ``call_log`` / ``results`` 等判官依赖的属性透传内层执行器。
    每行关联发起模型调用(model_call_sequence)、模型生成的 call_id 与
    tool.requested/completed 两个事件的全局序号(可观测性设计 §4.4)。
    """

    def __init__(self, inner: Any, recorder: RunRecorder) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_recorder", recorder)

    async def __call__(self, name: str, arguments: dict[str, Any]) -> Any:
        recorder = self._recorder
        sequence = recorder.next_tool_sequence()
        requested_seq = recorder.emit(
            EVENT_TOOL_REQUESTED, {"sequence": sequence, "tool": name, "arguments": arguments}
        )
        model_call_sequence = recorder.last_model_call_sequence
        pending = recorder.pop_pending_tool_call(name)
        call_id = pending.get("callId")
        if pending.get("modelCallSequence") is not None:
            model_call_sequence = pending["modelCallSequence"]
        started = time.perf_counter()
        try:
            result = await self._inner(name, arguments)
        except Exception as exc:  # noqa: BLE001 —— 失败也是一次可观察执行
            duration_ms = round((time.perf_counter() - started) * 1000)
            _status, category = classify_failure(str(exc))
            completed_seq = recorder.emit(
                EVENT_TOOL_COMPLETED,
                {"sequence": sequence, "tool": name, "status": "FAILED", "durationMs": duration_ms},
            )
            recorder.record_tool_call(
                ToolCallRow(
                    sequence=sequence,
                    tool_name=name,
                    arguments=dict(arguments or {}),
                    arguments_hash=payload_hash(arguments or {}),
                    status="FAILED",
                    result_summary={"error": str(exc)},
                    duration_ms=duration_ms,
                    fixture_hit=False,
                    error_category=category,
                    model_call_sequence=model_call_sequence,
                    call_id=call_id,
                    requested_event_sequence=requested_seq,
                    completed_event_sequence=completed_seq,
                    _t=started,
                )
            )
            raise
        duration_ms = round((time.perf_counter() - started) * 1000)
        summary = result if isinstance(result, dict) else {"value": json.dumps(result, ensure_ascii=False, default=str)}
        status = "SUCCESS" if not (isinstance(result, dict) and result.get("status") == "FAILED") else "FAILED"
        # NOT_IN_FIXTURE:该组参数没有冻结返回,未命中冻结数据(设计 §6.2)
        fixture_hit = not (isinstance(result, dict) and result.get("error_code") == "NOT_IN_FIXTURE")
        completed_seq = recorder.emit(
            EVENT_TOOL_COMPLETED,
            {"sequence": sequence, "tool": name, "status": status, "durationMs": duration_ms},
        )
        recorder.record_tool_call(
            ToolCallRow(
                sequence=sequence,
                tool_name=name,
                arguments=dict(arguments or {}),
                arguments_hash=payload_hash(arguments or {}),
                status=status,
                result_summary=summary,
                result_hash=payload_hash(summary),
                duration_ms=duration_ms,
                fixture_hit=fixture_hit,
                model_call_sequence=model_call_sequence,
                call_id=call_id,
                requested_event_sequence=requested_seq,
                completed_event_sequence=completed_seq,
                _t=started,
            )
        )
        # ToolMessage 回填紧随执行器返回(loop.py):结果进入下一轮模型上下文
        recorder.emit(
            EVENT_MODEL_RESULT_APPENDED,
            {"sequence": sequence, "tool": name, "status": status, "modelCallSequence": model_call_sequence},
        )
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


# ── 治理审计 → guardrail_checks / DENIED tool_calls ─────────────────────


def record_governance_audits(recorder: RunRecorder, audits: list[Any], observations: list[Any]) -> None:
    """GovernanceMiddleware 审计(G7)转明细:拦截写 DENIED 工具行 + action 检查行。"""

    for audit in audits:
        allowed = str(audit.status) == "SUCCESS"
        row = GuardrailCheckRow(
            sequence=recorder.next_guard_sequence(),
            stage="action",
            decision="allow" if allowed else "block",
            audit_code=getattr(audit, "audit_code", None),
            reasons=[] if allowed else [f"status={audit.status}"],
            tool_name=audit.tool_name,
            model_call_sequence=recorder.last_model_call_sequence,
            duration_ms=int(getattr(audit, "elapsed_ms", 0) or 0),
            detail={"status": str(audit.status)},
            _t=time.perf_counter(),
        )
        if allowed:
            recorder.record_guardrail_check(row)
            continue
        # 治理拦截的调用同样来自模型输出:消费配对项(含发起模型调用序号),
        # 防队列泄漏;发起序号以 stash 时固定值为准,不用当前最近一次冒充
        pending = recorder.pop_pending_tool_call(str(audit.tool_name or ""))
        denied_model_call_sequence = (
            pending["modelCallSequence"]
            if pending.get("modelCallSequence") is not None
            else recorder.last_model_call_sequence
        )
        tool_row = ToolCallRow(
            sequence=recorder.next_tool_sequence(),
            tool_name=audit.tool_name,
            arguments={"summary": str(getattr(audit, "arguments_summary", "") or "")},
            arguments_hash=payload_hash(getattr(audit, "arguments_summary", "") or ""),
            status="DENIED",
            duration_ms=int(getattr(audit, "elapsed_ms", 0) or 0),
            audit_code=getattr(audit, "audit_code", None),
            fixture_hit=False,
            model_call_sequence=denied_model_call_sequence,
            call_id=pending.get("callId"),
            _t=time.perf_counter(),
        )
        recorder.record_tool_call(tool_row)
        row.tool_call_sequence = tool_row.sequence
        recorder.record_guardrail_check(row)
    _ = observations  # 数据面质量检查在上层 data_quality 阶段落位,此处不重复


def record_output_guardrail(recorder: RunRecorder, guard_report: Any) -> None:
    """Output Guardrail(response 时点):违规 → modify,干净 → 单行 allow。"""

    violations = list(getattr(guard_report, "violations", []) or [])
    if not violations:
        recorder.record_guardrail_check(
            GuardrailCheckRow(
                sequence=recorder.next_guard_sequence(),
                stage="response",
                decision="allow",
                reasons=["出口检查通过"],
                duration_ms=0,
                _t=time.perf_counter(),
            )
        )
        return
    for violation in violations:
        recorder.record_guardrail_check(
            GuardrailCheckRow(
                sequence=recorder.next_guard_sequence(),
                stage="response",
                decision="modify",
                audit_code=str(violation.check_name),
                rule_ids=[str(violation.check_name)],
                reasons=[str(violation.detail)],
                duration_ms=0,
                detail={"severity": str(violation.severity)},
                _t=time.perf_counter(),
            )
        )


# ── 上下文构建报告 → context_builds 落库载荷 ─────────────────────────────

COMPRESSION_VERSION = "structured-text-v1"


def context_build_payload(
    result: ContextBuildResult,
    items: list[ContextItem],
    *,
    duration_ms: int,
    status: str = "COMPLETE",
    error_code: str | None = None,
    tokenizer_version: str = CONSERVATIVE_TOKENIZER_VERSION,
    compression_version: str = COMPRESSION_VERSION,
) -> dict[str, Any]:
    """ContextBuildResult → data 服务 ``/runs/{id}/context-builds`` 请求体。

    items 必须是本次构建的请求条目(与 report.decisions 一一对应)。
    tokenizer_version/compression_version 可按批次口径覆盖,默认保守口径 + structured-text-v1。
    """

    report = result.report
    counter = ConservativeTokenCounter()
    item_rows = [
        {
            "itemKey": item.item_id,
            "itemType": item.item_type,
            "classification": item.classification.value,
            "content": item.content,
            "sourceId": item.source_id,
            "ownerId": item.owner_id,
            "observedAt": item.observed_at,
            "priority": item.priority,
            "trusted": item.trusted,
            "rawTokens": counter.count(item.content),
            "contentHash": payload_hash(item.content),
            "sequence": item.sequence,
        }
        for item in items
    ]
    decision_rows = []
    for order, decision in enumerate(report.decisions):
        source_item = next((item for item in items if item.item_id == decision.item_id), None)
        decision_rows.append(
            {
                "itemKey": decision.item_id,
                "action": decision.action.value,
                "reason": decision.reason,
                "inputTokens": decision.input_tokens,
                "outputTokens": decision.output_tokens,
                "outputContent": decision.output_content,
                "outputHash": payload_hash(decision.output_content) if decision.output_content else None,
                "referenceId": decision.source_id or (source_item.source_id if source_item else None),
                "decisionOrder": order,
            }
        )
    message_rows = [
        {
            "messageOrder": order,
            "role": message.role,
            "content": message.content,
            "contentHash": payload_hash(message.content),
            "tokens": counter.count(message.content),
        }
        for order, message in enumerate(result.messages)
    ]
    compressed = [decision for decision in report.decisions if decision.action is ContextAction.COMPRESSED]
    return {
        "strategy": report.strategy.value,
        "tokenizerVersion": tokenizer_version,
        "compressionVersion": compression_version,
        "tokenBudget": report.token_budget,
        "originalTokens": report.original_tokens,
        "workingTokens": report.working_tokens,
        "compressionInputTokens": sum(decision.input_tokens for decision in compressed),
        "compressionOutputTokens": sum(decision.output_tokens for decision in compressed),
        "durationMs": max(0, duration_ms),
        "requiredRetained": report.required_retained,
        "budgetFit": report.budget_fit,
        "referencesValid": True,
        "instructionIsolated": True,
        "status": status,
        "errorCode": error_code,
        "counts": report.counts,
        "warnings": list(report.warnings),
        "items": item_rows,
        "decisions": decision_rows,
        "messages": message_rows,
    }


# ── 九段统一工件(评测文档 §9)───────────────────────────────────────────

ARTIFACT_VERSION = 1


def _artifact_context_section(record: RunRecord) -> dict[str, Any]:
    """工件 context 段:真源是上下文构建报告;未走构建器的组如实标注。"""

    build = record.context_build
    if not build:
        return {
            "strategy": record.context_strategy,
            "raw_tokens": 0,
            "working_tokens": 0,
            "required_retained": None,
            "selected_items": [],
            "omitted_items": [],
            "note": "本组模型输入不经 ContextBuilder",
        }
    decisions = build.get("decisions") or []
    selected = [
        str(row.get("itemKey")) for row in decisions if row.get("action") in {"kept", "compressed", "referenced"}
    ]
    omitted = [str(row.get("itemKey")) for row in decisions if row.get("action") in {"omitted", "isolated"}]
    section: dict[str, Any] = {
        "strategy": build.get("strategy") or record.context_strategy,
        "raw_tokens": int(build.get("originalTokens") or 0),
        "working_tokens": int(build.get("workingTokens") or 0),
        "required_retained": bool(build.get("requiredRetained")),
        "budget_fit": bool(build.get("budgetFit")),
        "token_budget": int(build.get("tokenBudget") or 0),
        "counts": dict(build.get("counts") or {}),
        "selected_items": selected,
        "omitted_items": omitted,
        "tokenizer_version": build.get("tokenizerVersion"),
        "compression_version": build.get("compressionVersion"),
    }
    if build.get("errorCode"):
        section["error_code"] = build["errorCode"]
    return section


def build_run_artifact(record: RunRecord) -> dict[str, Any]:
    """按 §9 schema 组装九段工件;artifact_hash 覆盖前八段,可复算验证。"""

    timed: list[tuple[float, dict[str, Any]]] = []
    for row in record.model_calls:
        step: dict[str, Any] = {
            "type": "model",
            "decision": row.decision,
            "latency_ms": row.duration_ms,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
        }
        if row.tools:
            step["tools"] = row.tools
        if row.status != "COMPLETE":
            step["status"] = row.status
            step["error_category"] = row.error_category
        timed.append((row._t, step))
    for row in record.tool_calls:
        timed.append(
            (
                row._t,
                {
                    "type": "tool",
                    "name": row.tool_name,
                    "arguments": row.arguments,
                    "status": row.status,
                    "audit_code": row.audit_code,
                    "duration_ms": row.duration_ms,
                    "observation": {"summary": row.result_summary},
                    "source": "fixture" if row.fixture_hit else None,
                    "data_time": row.source_time,
                },
            )
        )
    ordered = sorted(timed, key=lambda item: item[0])
    steps = [{"seq": index, **step} for index, (_t, step) in enumerate(ordered, start=1)]
    measurements = record.measurements or {}
    judgment = dict(record.judgment)
    judgment.setdefault("validity", validity_of(record.status))
    artifact = {
        "artifact_version": ARTIFACT_VERSION,
        "run_id": record.run_id or record.run_key,
        "batch_id": record.batch_id or "",
        "status": record.status,
        "validity": validity_of(record.status),
        "case": {
            "id": record.case_id,
            "version": record.case_version,
            "variant": record.variant_id,
            "message": record.message,
            "scene": record.scene,
            "authenticated": record.authenticated,
            "history_count": record.history_turns,
        },
        "experiment": {
            "agent_mode": record.agent_mode,
            "context_strategy": record.context_strategy,
            "model": record.model,
            "repeat_index": record.repeat_index,
        },
        "provenance": {
            "git_commit": record.provenance.get("git_commit", "unknown"),
            "prompt_hash": record.provenance.get("prompt_hash", ""),
            "tool_catalog_hash": record.provenance.get("tool_catalog_hash", ""),
            # 本运行实际使用的冻结工具集(按用例取集后与全局集区分;旧运行无此键)
            "fixture_set_id": record.provenance.get("fixture_set_id"),
            "snapshot_hash": record.snapshot_hash,
            "snapshot_id": record.snapshot_id,
            "judge_version": record.provenance.get("judge_version", ""),
            "tokenizer_version": record.provenance.get("tokenizer_version", TOKENIZER_VERSION),
            # 运行配置快照(混合路线阶段A3):配置体 + SHA-256;旧运行无此键
            "per_run_config": record.provenance.get("per_run_config"),
            "config_hash": record.provenance.get("config_hash", ""),
        },
        "context": _artifact_context_section(record),
        "steps": steps,
        "visible_tools": list(record.visible_tools),
        "guardrail_checks": [
            {
                "sequence": row.sequence,
                "stage": row.stage,
                "decision": row.decision,
                "audit_code": row.audit_code,
                "tool_name": row.tool_name,
            }
            for row in record.guardrail_checks
        ],
        "result": {
            "answer_excerpt": record.answer_excerpt[:200],
            "audit_codes": sorted({row.audit_code for row in record.tool_calls if row.audit_code}),
            "error_category": record.error_category,
        },
        "judgment": judgment,
        "timing": {
            "context_ms": measurements.get("contextCollectMs", 0),
            "llm_ms": measurements.get("llmMs", 0),
            "tool_ms": measurements.get("toolMs", 0),
            "guardrail_ms": measurements.get("guardrailMs", 0),
            "judgment_ms": measurements.get("judgmentMs", 0),
            "first_output_ms": measurements.get("firstOutputMs"),
            "duration_ms": record.duration_ms,
        },
        "tokens": {
            "prompt": measurements.get("promptTokens", 0),
            "completion": measurements.get("completionTokens", 0),
            "compression": 0,
            "estimated": bool((record.judgment or {}).get("tokens_estimated")),
        },
    }
    artifact = _integral_floats_to_int(artifact)
    artifact["artifact_hash"] = artifact_hash_of(artifact)
    return artifact


def _integral_floats_to_int(value: Any) -> Any:
    """整值浮点规范化为 int(1.0 → 1)。

    Python json.dumps 序列化 1.0 为 "1.0",发布器(JS JSON.stringify)为 "1",
    artifact_hash 跨语言复算随之不一致。工件构建时统一收敛为整数,两种语言
    的规范化文本恒同。非整值浮点(如 13/15)两边都是最短表示,天然一致;
    指数形式的极小/极大浮点仍有 "1e-07" vs "1e-7" 差异,工件指标不出现该量级。
    """

    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _integral_floats_to_int(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_integral_floats_to_int(item) for item in value]
    return value


def artifact_hash_of(artifact: dict[str, Any]) -> str:
    body = {key: value for key, value in artifact.items() if key != "artifact_hash"}
    return payload_hash(body)


def verify_artifact_hash(artifact: dict[str, Any]) -> bool:
    return artifact.get("artifact_hash") == artifact_hash_of(artifact)
