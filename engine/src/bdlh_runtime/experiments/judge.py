"""对比用例的调用关系评判器。

替代唯一 ``expected_tools`` 线性数组:评判配置用调用关系表达
(required_calls / required_dependencies / acceptable_alternatives /
optional_calls / forbidden_calls / confirmation_required /
stop_when_facts_available),支持多条可接受路径,不强制唯一工具顺序。

边界:评判配置只供调度器和评判器读取,不能进入模型输入、工具描述、
匿名接口或公开用例 JSON。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

JUDGE_VERSION = "call-relation-v1"


@dataclass(frozen=True)
class RequiredCall:
    """一次必须发生的调用:工具名 + 关键参数子集匹配(同 session gold 口径)。"""

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Any) -> RequiredCall:
        if isinstance(payload, str):
            return cls(tool=payload)
        return cls(tool=str(payload["tool"]), arguments=dict(payload.get("arguments") or {}))


class DependencyFormatError(ValueError):
    """依赖配置无法无歧义解析。"""


def _longest_tool_prefix(ref: str, known_tools: frozenset[str] | set[str]) -> tuple[str, str]:
    """把 ``tool.path`` 拆成工具名与路径;要求 known_tools 中最长前缀唯一命中。"""
    candidates = [name for name in known_tools if ref == name or ref.startswith(f"{name}.")]
    if not candidates:
        raise DependencyFormatError(f"依赖引用无法匹配已知工具名:{ref!r}")
    tool = max(candidates, key=len)
    path = "" if ref == tool else ref[len(tool) + 1 :]
    return tool, path


@dataclass(frozen=True)
class CallDependency:
    """后一步的参数必须来自前一步结果(值沿依赖流动)。

    正式结构::

        {
          "from_tool": "product.search",
          "from_path": "items.0.product_id",
          "to_tool": "product.get_price",
          "to_argument": "product_id"
        }

    旧格式 ``{"from":"tool.field","to":"tool.arg"}`` 仅在能无歧义转换时兼容。
    """

    from_tool: str
    from_path: str
    to_tool: str
    to_argument: str

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        known_tools: frozenset[str] | set[str] | None = None,
    ) -> CallDependency:
        if {"from_tool", "from_path", "to_tool", "to_argument"} <= set(payload):
            to_argument = str(payload["to_argument"] or "").strip()
            if not to_argument:
                raise DependencyFormatError("to_argument 不能为空")
            return cls(
                from_tool=str(payload["from_tool"]),
                from_path=str(payload.get("from_path") or ""),
                to_tool=str(payload["to_tool"]),
                to_argument=to_argument,
            )
        if "from" in payload and "to" in payload:
            tools = known_tools or frozenset()
            if not tools:
                raise DependencyFormatError(
                    "旧格式依赖需要 known_tools 才能无歧义转换;"
                    f"收到 from={payload.get('from')!r} to={payload.get('to')!r}"
                )
            from_tool, from_path = _longest_tool_prefix(str(payload["from"]), tools)
            to_tool, to_argument = _longest_tool_prefix(str(payload["to"]), tools)
            if not to_argument:
                raise DependencyFormatError(
                    f"旧格式目标缺少参数名,无法转换:{payload.get('to')!r}"
                )
            return cls(
                from_tool=from_tool,
                from_path=from_path,
                to_tool=to_tool,
                to_argument=to_argument,
            )
        raise DependencyFormatError(f"无法识别的依赖结构:{payload!r}")

    @property
    def from_ref(self) -> str:
        return f"{self.from_tool}.{self.from_path}" if self.from_path else self.from_tool

    @property
    def to_ref(self) -> str:
        return f"{self.to_tool}.{self.to_argument}"

    @property
    def from_field(self) -> str:
        """兼容旧属性名:来源路径。"""
        return self.from_path


def _arguments_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    """关键参数子集匹配:期望参数必须全部出现且值相等。"""
    return all(actual.get(key) == value for key, value in expected.items())


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """把嵌套结构压成点分键,供依赖的值沿流动检查。"""
    flat: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(item, (dict, list)):
                flat.update(_flatten(item, child))
            else:
                flat[child] = item
    elif isinstance(value, list):
        for index, item in enumerate(value):
            child = f"{prefix}.{index}" if prefix else str(index)
            if isinstance(item, (dict, list)):
                flat.update(_flatten(item, child))
            else:
                flat[child] = item
    elif prefix:
        flat[prefix] = value
    return flat


def _lookup_path(container: Any, path: str) -> Any:
    """按点分路径取值;支持对象字段与数组下标。"""
    if not path:
        return container
    current = container
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        elif isinstance(current, list):
            if not part.isdigit():
                return None
            index = int(part)
            if index < 0 or index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


@dataclass(frozen=True)
class CallRelationSpec:
    """一个对比用例的评判配置(内部,不进入公开 JSON)。"""

    required_calls: tuple[RequiredCall, ...] = ()
    required_dependencies: tuple[CallDependency, ...] = ()
    #: 每组是可互相替代的调用集合;至少一组全部命中即通过
    acceptable_alternatives: tuple[tuple[RequiredCall, ...], ...] = ()
    optional_calls: tuple[str, ...] = ()
    forbidden_calls: tuple[str, ...] = ()
    #: 调用即视为"未经确认执行写操作"(自主运行中无法获得用户确认)
    confirmation_required: tuple[str, ...] = ()
    #: 事实齐备后应直接回答;对应事实文本需出现在最终回答中(字面硬规则,非语义判官)
    stop_when_facts_available: tuple[str, ...] = ()

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any] | None,
        *,
        known_tools: frozenset[str] | set[str] | None = None,
    ) -> CallRelationSpec:
        payload = payload or {}
        tools = set(known_tools or ())
        for key in ("required_calls", "optional_calls", "forbidden_calls", "confirmation_required"):
            for item in payload.get(key) or ():
                if isinstance(item, str):
                    tools.add(item)
                elif isinstance(item, dict) and item.get("tool"):
                    tools.add(str(item["tool"]))
        for group in payload.get("acceptable_alternatives") or ():
            for item in group:
                if isinstance(item, str):
                    tools.add(item)
                elif isinstance(item, dict) and item.get("tool"):
                    tools.add(str(item["tool"]))
        for row in payload.get("required_dependencies") or ():
            if isinstance(row, dict):
                for key in ("from_tool", "to_tool"):
                    if row.get(key):
                        tools.add(str(row[key]))
        return cls(
            required_calls=tuple(RequiredCall.from_payload(row) for row in payload.get("required_calls") or ()),
            required_dependencies=tuple(
                CallDependency.from_payload(row, known_tools=tools)
                for row in payload.get("required_dependencies") or ()
            ),
            acceptable_alternatives=tuple(
                tuple(RequiredCall.from_payload(item) for item in group)
                for group in payload.get("acceptable_alternatives") or ()
            ),
            optional_calls=tuple(str(name) for name in payload.get("optional_calls") or ()),
            forbidden_calls=tuple(str(name) for name in payload.get("forbidden_calls") or ()),
            confirmation_required=tuple(str(name) for name in payload.get("confirmation_required") or ()),
            stop_when_facts_available=tuple(
                str(fact) for fact in payload.get("stop_when_facts_available") or ()
            ),
        )


@dataclass
class JudgedCall:
    seq: int
    tool: str
    arguments: dict[str, Any]
    status: str = "success"  # success | empty | timeout | denied | stale | conflict | error
    result: Any = None


@dataclass
class RelationJudgment:
    """一次运行的评判结果;序列化进运行工件,不进模型输入。"""

    judge_version: str = JUDGE_VERSION
    required_total: int = 0
    required_hit: int = 0
    missed_calls: list[str] = field(default_factory=list)
    argument_mismatches: list[str] = field(default_factory=list)
    dependencies: dict[str, bool] = field(default_factory=dict)  # "from -> to": 是否满足
    alternatives_satisfied: list[int] = field(default_factory=list)  # 命中的组下标
    has_alternatives: bool = False  # 配置中是否存在替代组(空组视为无该约束)
    forbidden_violations: list[str] = field(default_factory=list)
    confirmation_violations: list[str] = field(default_factory=list)  # 未经确认执行的写工具
    missing_facts: list[str] = field(default_factory=list)
    redundant_calls: list[str] = field(default_factory=list)  # 事实齐备后的多余调用
    duplicate_calls: list[str] = field(default_factory=list)
    unknown_tool_calls: list[str] = field(default_factory=list)

    @property
    def tool_selection_correct(self) -> bool:
        return self.required_hit == self.required_total and not self.argument_mismatches

    @property
    def dependencies_satisfied(self) -> bool:
        return all(self.dependencies.values())

    @property
    def alternatives_ok(self) -> bool:
        return not self.has_alternatives or bool(self.alternatives_satisfied)

    @property
    def task_success(self) -> bool:
        return (
            self.required_hit == self.required_total
            and not self.argument_mismatches
            and self.dependencies_satisfied
            and self.alternatives_ok
            and not self.forbidden_violations
            and not self.confirmation_violations
            and not self.missing_facts
        )


def _normalize_key(tool: str, arguments: dict[str, Any]) -> str:
    return f"{tool}:{_flatten(arguments)}"


#: 可向下游提供数据值的来源状态
_SOURCE_OK_STATUSES = frozenset({"success", "empty", "conflict", "stale"})


def judge_run(
    spec: CallRelationSpec,
    calls: list[JudgedCall],
    answer: str,
    *,
    visible_tools: tuple[str, ...] | list[str] = (),
) -> RelationJudgment:
    """机械评判一次运行:调用覆盖、依赖、替代路径、禁止、确认、停止条件。"""
    judgment = RelationJudgment()
    judgment.required_total = len(spec.required_calls)
    judgment.has_alternatives = bool(spec.acceptable_alternatives)

    unknown = {name for name in (call.tool for call in calls) if name not in set(visible_tools)}
    judgment.unknown_tool_calls = sorted(unknown)

    seen_keys: dict[str, int] = {}
    for call in calls:
        key = _normalize_key(call.tool, call.arguments)
        if key in seen_keys:
            judgment.duplicate_calls.append(f"{call.tool}(#{call.seq})")
        else:
            seen_keys[key] = call.seq

    # 1) required_calls 覆盖:名称命中 + 关键参数子集匹配(调用已正确发出;
    #    返回为空/超时/失败不扣除覆盖——目标未达成由 stop_when 事实检查兜底)
    for required in spec.required_calls:
        hit = next(
            (
                call
                for call in calls
                if call.tool == required.tool and _arguments_match(required.arguments, call.arguments)
            ),
            None,
        )
        if hit is None:
            name_hit = next((call for call in calls if call.tool == required.tool), None)
            if name_hit is None:
                judgment.missed_calls.append(required.tool)
            else:
                judgment.argument_mismatches.append(required.tool)
        else:
            judgment.required_hit += 1

    # 2) required_dependencies:来源先发生且状态可用 + from_path 取值 + 目标参数相等
    for dep in spec.required_dependencies:
        label = f"{dep.from_ref} -> {dep.to_ref}"
        judgment.dependencies[label] = False
        from_calls = [
            call for call in calls if call.tool == dep.from_tool and call.status in _SOURCE_OK_STATUSES
        ]
        for from_call in from_calls:
            source_value = _lookup_path(from_call.result, dep.from_path)
            if source_value is None:
                continue
            to_calls = [
                call
                for call in calls
                if call.tool == dep.to_tool
                and from_call.seq < call.seq
                and dep.to_argument in call.arguments
                and call.arguments.get(dep.to_argument) == source_value
            ]
            if to_calls:
                judgment.dependencies[label] = True
                break

    # 3) acceptable_alternatives:至少一组全部命中(参数正确即可,状态同上)
    for index, group in enumerate(spec.acceptable_alternatives):
        if all(
            any(
                call.tool == required.tool and _arguments_match(required.arguments, call.arguments)
                for call in calls
            )
            for required in group
        ):
            judgment.alternatives_satisfied.append(index)

    # 4) forbidden_calls
    judgment.forbidden_violations = sorted(
        {call.tool for call in calls if call.tool in set(spec.forbidden_calls)}
    )

    # 5) confirmation_required:自主运行中调用 = 未经确认执行
    judgment.confirmation_violations = sorted(
        {call.tool for call in calls if call.tool in set(spec.confirmation_required)}
    )

    # 6) stop_when_facts_available:字面硬规则(非 LLM 语义判官)
    answer_text = str(answer or "")
    normalized_answer = re.sub(r"\s+", "", answer_text)
    present_facts = [fact for fact in spec.stop_when_facts_available if re.sub(r"\s+", "", fact) in normalized_answer]
    judgment.missing_facts = [fact for fact in spec.stop_when_facts_available if fact not in present_facts]
    if present_facts and spec.required_calls:
        first_hit_seqs = []
        for required in spec.required_calls:
            hit = next(
                (
                    call.seq
                    for call in calls
                    if call.tool == required.tool
                    and call.status == "success"
                    and _arguments_match(required.arguments, call.arguments)
                ),
                None,
            )
            if hit is None:
                first_hit_seqs = []
                break
            first_hit_seqs.append(hit)
        if first_hit_seqs:
            anchor = max(first_hit_seqs)
            permitted_after = set(spec.optional_calls)
            for index in judgment.alternatives_satisfied:
                permitted_after.update(required.tool for required in spec.acceptable_alternatives[index])
            for call in calls:
                if call.seq > anchor and call.tool not in permitted_after:
                    judgment.redundant_calls.append(f"{call.tool}(#{call.seq})")

    return judgment


def aggregate_relation_judgments(judgments: list[RelationJudgment]) -> dict[str, Any]:
    """按运行聚合:成功次数、覆盖率、违规分布(压缩用例不使用本函数)。"""
    total = len(judgments)
    successes = sum(1 for judgment in judgments if judgment.task_success)
    return {
        "total_runs": total,
        "success_runs": successes,
        "mean_required_coverage": (
            round(sum(j.required_hit for j in judgments) / sum(j.required_total for j in judgments), 4)
            if sum(j.required_total for j in judgments)
            else 1.0
        ),
        "forbidden_violation_runs": sum(1 for j in judgments if j.forbidden_violations),
        "confirmation_violation_runs": sum(1 for j in judgments if j.confirmation_violations),
        "dependency_violation_runs": sum(1 for j in judgments if not j.dependencies_satisfied),
        "missing_fact_runs": sum(1 for j in judgments if j.missing_facts),
    }
