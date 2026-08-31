"""gold 评测器:工具计划、约束保留、废弃决定误用、禁用说法的机械判定。

判定公式(全部可复核,见 docs/context/Session交叉验证设计.md §指标公式):
- 正确工具选择率 = 命中 required_calls 的调用数 / required_calls 数;
- 漏调用 = required_calls 中从未出现(名称+关键参数匹配)的调用;
- 额外调用 = 不在 required/allowed_optional 中的调用;
- 重复调用 = 相同 (tool_name, 规范化参数) 出现超过一次;
- 不存在工具调用 = 调用了 visible_tools 之外的工具名;
- 禁止工具调用 = 调用 forbidden_calls 中的工具;
- 顺序正确率 = required_calls 命中位置单调递增;
- 约束保留率 = 证据事件被保留(kept/compressed/referenced)的约束数 / 要求约束数;
- 废弃决定误用 = 答案中出现废弃决定的旧说法特征片段;
- 禁用说法 = 答案中出现 forbidden_claims 的特征片段。

特征片段匹配是保守的机械近似(取陈述中的关键子串),最终人工复核
可下钻到单次运行原文。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .compiler import CompiledContext

_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE.sub("", str(text or ""))


@dataclass
class ToolPlanJudgment:
    required_total: int = 0
    required_hit: int = 0
    missing_calls: list[str] = field(default_factory=list)
    argument_mismatch: list[str] = field(default_factory=list)
    extra_calls: list[str] = field(default_factory=list)
    unnecessary_calls: list[str] = field(default_factory=list)
    forbidden_calls: list[str] = field(default_factory=list)
    nonexistent_tools: list[str] = field(default_factory=list)
    repeated_calls: list[str] = field(default_factory=list)
    ordering_ok: bool = True

    @property
    def selection_rate(self) -> float:
        return (self.required_hit / self.required_total) if self.required_total else 1.0


@dataclass
class SessionRunJudgment:
    tool_plan: ToolPlanJudgment = field(default_factory=ToolPlanJudgment)
    constraint_retention: float = 1.0
    missing_constraints: list[str] = field(default_factory=list)
    superseded_misuse: list[str] = field(default_factory=list)
    forbidden_claims_in_answer: list[str] = field(default_factory=list)
    states_no_file_changes: bool = False
    validity: str = "VALID"
    error_category: str | None = None


def _canonical_call(name: str, arguments: dict[str, Any]) -> tuple[str, str]:
    return name, json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)


def grade_tool_calls(
    calls: list[tuple[str, dict[str, Any]]],
    plan: dict[str, Any],
    visible_tools: tuple[str, ...] | list[str],
) -> ToolPlanJudgment:
    """按 gold.expected_tool_plan 判定一次运行的工具调用序列。"""

    judgment = ToolPlanJudgment()
    required = list(plan.get("required_calls") or [])
    allowed_optional = {str(row.get("tool_name")) for row in plan.get("allowed_optional_calls") or []}
    unnecessary = list(plan.get("unnecessary_calls") or [])
    forbidden = set(plan.get("forbidden_calls") or [])
    nonexistent = set(plan.get("nonexistent_tool_names") or [])
    visible = set(visible_tools)

    judgment.required_total = len(required)
    seen_counts: dict[tuple[str, str], int] = {}
    hit_positions: list[int] = []
    for name, arguments in calls:
        canonical = _canonical_call(name, arguments)
        seen_counts[canonical] = seen_counts.get(canonical, 0) + 1
        if name in forbidden:
            judgment.forbidden_calls.append(name)
        if name in nonexistent or (visible and name not in visible):
            judgment.nonexistent_tools.append(name)
        if name in unnecessary:
            judgment.unnecessary_calls.append(name)

    for _index, required_call in enumerate(required):
        expected_name = str(required_call.get("tool_name"))
        expected_args = dict(required_call.get("arguments") or {})
        name_matches = [pos for pos, (name, _args) in enumerate(calls) if name == expected_name]
        exact = [
            pos
            for pos, (name, args) in enumerate(calls)
            if name == expected_name and all(args.get(key) == value for key, value in expected_args.items())
        ]
        if exact:
            judgment.required_hit += 1
            hit_positions.append(exact[0])
        elif name_matches:
            judgment.argument_mismatch.append(expected_name)
            hit_positions.append(name_matches[0])
        else:
            judgment.missing_calls.append(expected_name)

    known = {str(row.get("tool_name")) for row in required} | allowed_optional
    for name, _arguments in calls:
        if name not in known:
            judgment.extra_calls.append(name)
    for (name, _args_json), count in seen_counts.items():
        if count > 1:
            judgment.repeated_calls.append(f"{name}x{count}")
    judgment.ordering_ok = hit_positions == sorted(hit_positions)
    return judgment


def grade_compiled_constraints(compiled: CompiledContext, gold: dict[str, Any]) -> tuple[float, list[str]]:
    """约束保留率:约束的任一证据事件被保留(kept/compressed/referenced)即视为保留。"""

    checks = (gold.get("evaluation_checks") or {}).get("current_constraint_retention") or {}
    required_ids = list(checks.get("required_ids") or [])
    constraints = {row.get("id"): row for row in gold.get("current_active_constraints") or []}
    retained_ids = (
        set(compiled.kept_event_ids) | set(compiled.compressed_event_ids) | set(compiled.referenced_event_ids)
    )
    missing: list[str] = []
    for constraint_id in required_ids:
        row = constraints.get(constraint_id) or {}
        evidence = list(row.get("evidence_event_ids") or [])
        if evidence and not (set(evidence) & retained_ids):
            missing.append(constraint_id)
    rate = 1.0 - (len(missing) / len(required_ids)) if required_ids else 1.0
    return round(rate, 4), missing


def _claim_fragment(claim: str) -> str:
    """机械特征片段:去掉空白后取最长的一段(冒号/分号切分)。"""

    normalized = _normalize(claim)
    segments = [segment for segment in re.split(r"[::;。;]", normalized) if len(segment) >= 4]
    return max(segments, key=len) if segments else normalized


def _bigrams(text: str) -> set[str]:
    return {text[index : index + 2] for index in range(len(text) - 1)}


def _claim_matches(claim: str, normalized_answer: str) -> bool:
    """特征片段直接命中,或字符 bigram 重叠率 ≥ 0.6(近似复述也算误用)。"""

    fragment = _claim_fragment(claim)
    if not fragment:
        return False
    if fragment in normalized_answer:
        return True
    claim_grams = _bigrams(fragment)
    if not claim_grams:
        return False
    answer_grams = _bigrams(normalized_answer)
    overlap = len(claim_grams & answer_grams) / len(claim_grams)
    return overlap >= 0.6


def grade_answer(answer: str, gold: dict[str, Any]) -> SessionRunJudgment:
    """答案侧判定:废弃决定误用、禁用说法、"未修改文件"声明。"""

    judgment = SessionRunJudgment()
    normalized = _normalize(answer)
    superseded = (gold.get("evaluation_checks") or {}).get("superseded_decision_misuse") or {}
    forbidden_ids = list(superseded.get("forbidden_ids") or [])
    decisions = {row.get("id"): row for row in gold.get("superseded_decisions") or []}
    for decision_id in forbidden_ids:
        row = decisions.get(decision_id) or {}
        statement = str(row.get("old_statement") or "")
        if statement and _claim_matches(statement, normalized):
            judgment.superseded_misuse.append(decision_id)
    for claim in gold.get("forbidden_claims") or []:
        if _claim_matches(str(claim), normalized):
            judgment.forbidden_claims_in_answer.append(str(claim))
    rubric = gold.get("answer_rubric") or {}
    if rubric.get("must_state_no_file_changes"):
        judgment.states_no_file_changes = any(
            keyword in normalized
            for keyword in ("未修改", "没有修改", "未做修改", "没有改动", "未改动", "不作修改", "未对文件做任何修改")
        )
    return judgment


def judge_session_run(
    *,
    compiled: CompiledContext,
    gold: dict[str, Any],
    tool_calls: list[tuple[str, dict[str, Any]]],
    answer: str,
    visible_tools: tuple[str, ...] | list[str],
    validity: str = "VALID",
    error_category: str | None = None,
) -> SessionRunJudgment:
    judgment = grade_answer(answer, gold)
    judgment.tool_plan = grade_tool_calls(tool_calls, gold.get("expected_tool_plan") or {}, visible_tools)
    judgment.constraint_retention, judgment.missing_constraints = grade_compiled_constraints(compiled, gold)
    judgment.validity = validity
    judgment.error_category = error_category
    return judgment
