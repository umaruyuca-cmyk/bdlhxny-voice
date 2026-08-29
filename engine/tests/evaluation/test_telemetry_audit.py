"""运行遥测体检契约(阶段三:存储量/缺失遥测/事件乱序监控,设计 §10)。

全部为内存构造的 detail 形状数据,不触网络。
"""

from __future__ import annotations

from bdlh_runtime.evaluation.telemetry_audit import audit_run_detail


def _detail(**overrides):
    detail = {
        "run": {"id": "r1", "status": "COMPLETE"},
        "events": [],
        "modelCalls": [],
        "toolCalls": [],
        "guardrailChecks": [],
        "measurements": [],
        "artifacts": [],
        "timeline": [],
    }
    detail.update(overrides)
    return detail


def _clean_detail():
    """一段合法的最小运行:事件连续、模型调用有消息、工具行有结果且关联。"""
    return _detail(
        events=[
            {"sequence": 1, "eventType": "run.started", "payload": {}},
            {"sequence": 2, "eventType": "model.completed", "payload": {"sequence": 1}},
            {"sequence": 3, "eventType": "tool.requested", "payload": {"sequence": 1, "tool": "t"}},
            {"sequence": 4, "eventType": "tool.completed", "payload": {"sequence": 1, "tool": "t"}},
            {"sequence": 5, "eventType": "run.completed", "payload": {}},
        ],
        modelCalls=[
            {
                "sequence": 1,
                "decision": "call_tool",
                "status": "COMPLETE",
                "messages": [{"messageOrder": 0, "role": "user", "content": "q", "contentHash": "sha256:x"}],
                "tool_schemas": [{"type": "function", "function": {"name": "t"}}],
            }
        ],
        toolCalls=[
            {
                "sequence": 1,
                "tool_name": "t",
                "status": "SUCCESS",
                "model_call_sequence": 1,
                "result_summary": {"value": 1},
            }
        ],
    )


def test_clean_run_passes_with_storage_breakdown():
    audit = audit_run_detail(_clean_detail())
    assert audit["ok"] is True
    assert audit["sequenceIssues"] == []
    assert audit["coverageIssues"] == []
    assert audit["auditVersion"] == 1
    assert set(audit["storage"]) == {"events", "modelCalls", "toolCalls", "guardrailChecks", "total"}
    assert audit["storage"]["total"] > 0
    assert audit["storage"]["total"] == sum(
        audit["storage"][key] for key in ("events", "modelCalls", "toolCalls", "guardrailChecks")
    )


def test_sequence_gap_and_missing_requested_event_detected():
    detail = _clean_detail()
    detail["events"] = [event for event in detail["events"] if event["sequence"] != 3]
    audit = audit_run_detail(detail)
    assert audit["ok"] is False
    assert any("不连续" in item for item in audit["sequenceIssues"])
    assert any("没有 tool.requested" in item for item in audit["sequenceIssues"])


def test_dangling_event_reference_detected():
    detail = _clean_detail()
    detail["events"].append({"sequence": 6, "eventType": "model.completed", "payload": {"sequence": 99}})
    audit = audit_run_detail(detail)
    assert any("悬空" in item and "99" in item for item in audit["sequenceIssues"])


def test_tool_completed_order_inversion_detected():
    detail = _clean_detail()
    for event in detail["events"]:
        if event["eventType"] == "tool.requested":
            event["sequence"] = 4
        elif event["eventType"] == "tool.completed":
            event["sequence"] = 3
    detail["events"].sort(key=lambda event: event["sequence"])
    audit = audit_run_detail(detail)
    assert any("早于" in item for item in audit["sequenceIssues"])


def test_call_tool_without_tool_rows_detected():
    detail = _clean_detail()
    detail["toolCalls"] = []
    audit = audit_run_detail(detail)
    assert any("call_tool" in item and "没有工具行" in item for item in audit["coverageIssues"])


def test_success_tool_without_result_summary_detected():
    detail = _clean_detail()
    detail["toolCalls"][0]["result_summary"] = {}
    audit = audit_run_detail(detail)
    assert any("没有结果摘要" in item for item in audit["coverageIssues"])


def test_tool_call_without_model_link_detected():
    detail = _clean_detail()
    detail["toolCalls"][0]["model_call_sequence"] = None
    audit = audit_run_detail(detail)
    assert any("缺少发起模型调用关联" in item for item in audit["coverageIssues"])


def test_complete_model_call_without_messages_detected():
    detail = _clean_detail()
    detail["modelCalls"][0]["messages"] = []
    audit = audit_run_detail(detail)
    assert any("没有消息快照" in item for item in audit["coverageIssues"])
