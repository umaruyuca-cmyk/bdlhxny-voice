"""运行遥测体检(阶段三:存储量/缺失遥测/事件乱序监控,设计 §10)。

纯函数消费 data 服务 detail 响应,产出三类结论:
- ``sequenceIssues``:事件序号不连续(缺口/重复)、tool.requested/completed
  相对顺序倒置、事件引用的明细行悬空;
- ``coverageIssues``:decision=call_tool 的模型调用没有工具行(含 DENIED)
  指向、工具行缺发起模型调用关联、COMPLETE 模型调用无消息快照、
  SUCCESS 工具调用无结果摘要;
- ``storage``:明细四类的 canonical JSON 字节数与合计(口径与落库
  ``run_measurements.telemetry_bytes`` 一致)。

只旁路检查,不改变任何数据;随 detail 响应内嵌返回,页面免二次请求。
"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.evaluation.run_telemetry import canonical_json

AUDIT_VERSION = 1


def _canonical_bytes(payload: Any) -> int:
    return len(canonical_json(payload).encode("utf-8"))


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sequence_issues(events: list[dict[str, Any]], model_seqs: set[int], tool_seqs: set[int], guard_seqs: set[int]) -> list[str]:
    issues: list[str] = []
    sequences = [_int(event.get("sequence")) for event in events]
    if any(seq is None for seq in sequences):
        issues.append("存在非数字事件序号")
        sequences = [seq for seq in sequences if seq is not None]
    if sequences:
        unique = sorted(set(sequences))
        expected = list(range(unique[0], unique[0] + len(unique)))
        if unique != expected:
            issues.append(f"事件序号不连续:期望 {expected[0]}..{expected[-1]},实际缺失 {sorted(set(expected) - set(unique))}")
        duplicated = len(sequences) - len(unique)
        if duplicated:
            issues.append(f"存在 {duplicated} 条重复序号事件")
    # tool.requested → tool.completed 的全局顺序不得倒置
    requested_at: dict[int, int] = {}
    completed_at: dict[int, int] = {}
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        ref = _int((payload or {}).get("sequence"))
        if ref is None:
            continue
        if event.get("eventType") == "tool.requested":
            requested_at.setdefault(ref, _int(event.get("sequence")) or 0)
        elif event.get("eventType") == "tool.completed":
            completed_at.setdefault(ref, _int(event.get("sequence")) or 0)
    for ref, completed in completed_at.items():
        requested = requested_at.get(ref)
        if requested is None:
            issues.append(f"工具行 {ref} 有 tool.completed 但没有 tool.requested 事件")
        elif completed < requested:
            issues.append(f"工具行 {ref} 的 tool.completed(事件#{completed})早于 tool.requested(事件#{requested})")
        if ref not in tool_seqs:
            issues.append(f"事件引用的工具行 {ref} 在 tool_calls 中不存在(悬空)")
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        ref = _int((payload or {}).get("sequence"))
        if ref is None:
            continue
        event_type = str(event.get("eventType") or "")
        if event_type == "model.completed" and ref not in model_seqs:
            issues.append(f"model.completed 引用的模型调用 {ref} 在 model_calls 中不存在(悬空)")
        if event_type == "guardrail.completed" and ref not in guard_seqs:
            issues.append(f"guardrail.completed 引用的治理行 {ref} 在 guardrail_checks 中不存在(悬空)")
    return issues


def _coverage_issues(
    model_calls: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
) -> list[str]:
    issues: list[str] = []
    tools_by_model: dict[int, list[dict[str, Any]]] = {}
    for call in tool_calls:
        ref = _int(call.get("model_call_sequence"))
        if ref is None:
            issues.append(f"工具行 {call.get('sequence')} 缺少发起模型调用关联(旧数据或链路缺陷)")
        else:
            tools_by_model.setdefault(ref, []).append(call)
    for call in model_calls:
        sequence = _int(call.get("sequence"))
        if sequence is None:
            continue
        if str(call.get("decision")) == "call_tool" and not tools_by_model.get(sequence):
            issues.append(f"模型调用 {sequence} 决策为 call_tool,但没有工具行(含 DENIED)指向它")
        if str(call.get("status")) == "COMPLETE" and not (call.get("messages") or []):
            issues.append(f"模型调用 {sequence} 状态为 COMPLETE 但没有消息快照")
    for call in tool_calls:
        if str(call.get("status")) == "SUCCESS" and not call.get("result_summary"):
            issues.append(f"工具行 {call.get('sequence')} 状态为 SUCCESS 但没有结果摘要")
    return issues


def audit_run_detail(detail: dict[str, Any]) -> dict[str, Any]:
    """对 detail 响应做只读体检;输出可直接内嵌回 detail 响应。"""
    events = list(detail.get("events") or [])
    model_calls = list(detail.get("modelCalls") or [])
    tool_calls = list(detail.get("toolCalls") or [])
    guardrails = list(detail.get("guardrailChecks") or [])
    model_seqs = {_int(call.get("sequence")) for call in model_calls} - {None}
    tool_seqs = {_int(call.get("sequence")) for call in tool_calls} - {None}
    guard_seqs = {_int(check.get("sequence")) for check in guardrails} - {None}
    sequence_issues = _sequence_issues(events, model_seqs, tool_seqs, guard_seqs)
    coverage_issues = _coverage_issues(model_calls, tool_calls)
    storage = {
        "events": _canonical_bytes(events),
        "modelCalls": _canonical_bytes(model_calls),
        "toolCalls": _canonical_bytes(tool_calls),
        "guardrailChecks": _canonical_bytes(guardrails),
    }
    storage["total"] = sum(storage.values())
    return {
        "auditVersion": AUDIT_VERSION,
        "sequenceIssues": sequence_issues,
        "coverageIssues": coverage_issues,
        "storage": storage,
        "ok": not sequence_issues and not coverage_issues,
    }


__all__ = ["AUDIT_VERSION", "audit_run_detail"]
