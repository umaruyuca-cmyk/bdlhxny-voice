"""session-cross 落库载荷与发布器测试(fake DataClient,无网络)。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bdlh_runtime.context import ContextClassification, ContextItem, ContextRole
from bdlh_runtime.data_client import DataServiceError
from bdlh_runtime.evaluation.session_cross_db import (
    build_batch_payload,
    build_run_persist_plan,
    build_tool_calls_payload,
    persist_plan,
    persist_session_cross_report,
    sanitize_for_print,
)
from bdlh_runtime.session import SessionCompiler, load_session, load_variants
from bdlh_runtime.session.publisher import publish_session_cross

_CASE_DIR = Path(__file__).resolve().parents[2] / "var" / "cases" / "ctx-session-touchstone-design-01"


class FakeDataClient:
    """记录调用序列的假客户端;fail_on 可注入连接失败。"""

    def __init__(self, *, fail_on: str | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.fail_on = fail_on
        self._counter = 0

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter:04d}"

    def _record(self, name: str, payload: Any = None) -> None:
        if self.fail_on == name:
            raise DataServiceError(f"injected failure at {name}")
        self.calls.append((name, payload))

    def create_batch(self, *, name: str, fixed_conditions: dict[str, Any]) -> str:
        self._record("create_batch", {"name": name, "fixedConditions": fixed_conditions})
        return self._next_id("batch")

    def create_run(self, payload: dict[str, Any]) -> str:
        self._record("create_run", payload)
        return self._next_id("run")

    def save_context_build(self, run_id: str, build: dict[str, Any]) -> None:
        self._record("save_context_build", {"run_id": run_id, **build})

    def save_tool_calls(self, run_id: str, calls: list[dict[str, Any]]) -> None:
        self._record("save_tool_calls", {"run_id": run_id, "calls": calls})

    def save_evaluation(
        self, run_id: str, *, checks: dict, metrics: dict, valid_run: bool, status: str, evaluator_version: str
    ) -> None:
        self._record(
            "save_evaluation",
            {
                "run_id": run_id,
                "evaluatorVersion": evaluator_version,
                "validRun": valid_run,
                "status": status,
                "checks": checks,
                "metrics": metrics,
            },
        )

    def complete_run(self, run_id: str, output: dict[str, Any], *, status: str = "COMPLETE",
                     error_category: str | None = None, error_message: str | None = None) -> None:
        self._record("complete_run", {"run_id": run_id, "status": status, "output": output,
                                      "errorCategory": error_category, "errorMessage": error_message})

    def save_artifact(self, run_id: str, *, artifact_type: str, storage_ref: str,
                      content_hash: str, public: bool = False) -> None:
        self._record("save_artifact", {"run_id": run_id, "artifactType": artifact_type,
                                       "storageRef": storage_ref, "contentHash": content_hash, "public": public})

    def complete_batch(self, batch_id: str, status: str) -> None:
        self._record("complete_batch", {"batch_id": batch_id, "status": status})


def _items() -> list[ContextItem]:
    return [
        ContextItem("system-prompt", "公共规则。", ContextClassification.REQUIRED, role=ContextRole.SYSTEM, sequence=-1000),
        ContextItem("evt-1", "用户消息。", ContextClassification.COMPRESSIBLE, sequence=1),
        ContextItem("evt-2", "助手消息。", ContextClassification.COMPRESSIBLE, role=ContextRole.ASSISTANT, sequence=2),
    ]


def _report() -> dict[str, Any]:
    judgment = {
        "tool_plan": {"selection_rate": 0.67, "required_total": 3, "required_hit": 2, "missing_calls": ["code.read"]},
        "constraint_retention": 1.0,
        "missing_constraints": [],
        "superseded_misuse": [],
        "forbidden_claims_in_answer": [],
        "states_no_file_changes": True,
        "validity": "VALID",
        "error_category": None,
    }
    invalid_judgment = dict(judgment, validity="INVALID", error_category="LLM_TIMEOUT")
    run_valid = {
        "run_key": "case:budgeted-session:baseline-tool-calling:0",
        "repeat_index": 0,
        "answer": "结论:使用 PostgreSQL。未修改任何文件。",
        "error": None,
        "validity": "VALID",
        "duration_ms": 1234,
        "tool_calls": [{"tool": "file.read", "arguments": {"path": "a.md"}}],
        "mock_records": [
            {"step": 1, "tool_name": "file.read", "arguments": {"path": "a.md"}, "fixture_id": "fx-1",
             "status": "success", "result": {"content_excerpt": "…"}, "simulated": True},
            {"step": 2, "tool_name": "file.read", "arguments": {"path": "bad.md"}, "fixture_id": None,
             "status": "error", "result": {"error_code": "FILE_NOT_IN_FIXTURE"}, "simulated": True},
        ],
        "judgment": judgment,
    }
    run_invalid = dict(run_valid, run_key="case:budgeted-session:baseline-tool-calling:1",
                       repeat_index=1, answer="", error="运行超时(timed out):单运行熔断",
                       validity="INVALID", mock_records=[], judgment=invalid_judgment)
    return {
        "experiment_type": "session-cross",
        "evaluator_version": "session-cross-eval-v1",
        "case_id": "ctx-session-touchstone-design-01",
        "case_version": 1,
        "model": "test-model",
        "git_commit": "deadbeef",
        "generated_date": "20260824",
        "runs_per_cell": 2,
        "frozen_conditions": {"tokenizer_version": "conservative-cjk1-latin4-v1", "budgeted_scoring": "v1",
                              "llm_summary": False, "source_session_hash": "sha256:x"},
        "cells": [
            {"context_variant": "budgeted-session", "agent_mode": "baseline-tool-calling",
             "runs": [run_valid, run_invalid]},
        ],
        "by_variant": {}, "by_mode": {},
    }


def _artifacts() -> dict[str, Any]:
    session = load_session(_CASE_DIR / "ctx-session-touchstone-design-01.session.json")
    variants = load_variants(_CASE_DIR / "ctx-session-touchstone-design-01.variants.json")
    variant = next(row for row in variants["context_variants"] if row["variant_id"] == "budgeted-session")
    artifact = SessionCompiler().compile(session, variant, common_rules="规则")
    return {"budgeted-session": artifact}


# ── 载荷构造 ──────────────────────────────────────────────────────────────


def test_batch_payload_uses_session_cross_experiment_type() -> None:
    payload = build_batch_payload(_report(), name="session-cross-case-20260824")
    assert payload["experimentType"] == "session-cross"
    fixed = payload["fixedConditions"]
    assert fixed["evaluator_version"] == "session-cross-eval-v1"
    assert fixed["git_commit"] == "deadbeef"
    assert fixed["source_session_hash"] == "sha256:x"
    assert "compiled_context_hashes" not in fixed or isinstance(fixed.get("compiled_context_hashes", {}), dict)


def test_tool_calls_payload_maps_contract_fields() -> None:
    calls = build_tool_calls_payload(_report()["cells"][0]["runs"][0])
    assert [c["sequence"] for c in calls] == [1, 2]
    assert calls[0]["toolName"] == "file.read"
    assert calls[0]["status"] == "SUCCESS"
    assert calls[0]["fixtureHit"] is True
    assert calls[0]["resultSummary"]["fixture_id"] == "fx-1"
    assert calls[0]["resultSummary"]["simulated"] is True
    assert calls[1]["status"] == "FAILED"
    assert calls[1]["fixtureHit"] is False
    assert calls[0]["argumentsHash"].startswith("sha256:")
    # 契约字段名是 sequence(不是 step)、无 fixtureId 列
    assert all("fixtureId" not in c and "step" not in c for c in calls)


def test_run_plan_covers_valid_and_invalid_runs_with_contract_fields() -> None:
    artifacts = _artifacts()
    plan = build_run_persist_plan(_report(), artifacts=artifacts, items=_items(),
                                  tokenizer_version="conservative-cjk1-latin4-v1",
                                  fixture_set_id="ctx-session-touchstone-design-tools-v1")
    assert len(plan["runs"]) == 2  # INVALID 运行也构造载荷,不丢弃
    valid, invalid = plan["runs"]
    create = valid["payloads"]["create_run"]
    assert create["agentMode"] == "baseline-tool-calling"
    assert create["contextStrategy"] == "budgeted"
    assert create["snapshotId"] == "ctx-session-touchstone-design-tools-v1"
    assert create["modelConfig"]["original_agent_mode"] == "baseline-tool-calling"
    assert create["modelConfig"]["run_key"] == valid["run_key"]
    # context_build 载荷契约:必填字段齐备
    build = valid["payloads"]["context_build"]
    for key in ("strategy", "tokenizerVersion", "compressionVersion", "tokenBudget",
                "originalTokens", "workingTokens", "status", "items", "decisions", "messages"):
        assert key in build, f"context_build 缺 {key}"
    assert build["items"] and build["decisions"] and build["messages"]
    # INVALID 运行:状态真实透传,evaluation.validRun=False
    assert invalid["payloads"]["evaluation"]["validRun"] is False
    assert invalid["payloads"]["evaluation"]["status"] == "INVALID"
    assert invalid["payloads"]["complete"]["status"] == "INVALID"
    assert invalid["payloads"]["complete"]["errorCategory"] == "LLM_TIMEOUT"
    assert invalid["payloads"]["tool_calls"] == []  # 无 mock 记录不构造 calls
    assert plan["report_artifact"]["artifactType"] == "session_cross_report"
    assert plan["report_artifact"]["public"] is False
    # 隔离红线:载荷序列化后不得包含 gold 文件原文特征字段
    blob = json.dumps(plan, ensure_ascii=False, default=str)
    for marker in ("current_active_constraints", "superseded_decisions", "expected_tool_plan", "answer_rubric"):
        assert marker not in blob


def test_sanitize_for_print_redacts_key_like_fields() -> None:
    payload = {"apiKey": "sk-secret", "modelConfig": {"LLM_API_KEY": "sk-x", "runs": 3}}
    cleaned = sanitize_for_print(payload)
    assert cleaned["apiKey"] == "***redacted***"
    assert cleaned["modelConfig"]["LLM_API_KEY"] == "***redacted***"
    assert cleaned["modelConfig"]["runs"] == 3


# ── 持久化序列(fake DataClient)──────────────────────────────────────────


def test_persist_plan_calls_in_contract_order(tmp_path: Path) -> None:
    artifacts = _artifacts()
    plan = build_run_persist_plan(_report(), artifacts=artifacts, items=_items(),
                                  tokenizer_version="conservative-cjk1-latin4-v1")
    fake = FakeDataClient()
    result = persist_plan(fake, plan, report_json="{}", artifacts_dir=tmp_path)
    names = [name for name, _ in fake.calls]
    assert names[0] == "create_batch"
    assert names[-1] == "complete_batch"
    assert names.count("create_run") == 2
    # 每条运行:create_run → save_context_build → save_tool_calls → save_evaluation → complete_run
    assert names[1:6] == ["create_run", "save_context_build", "save_tool_calls", "save_evaluation", "complete_run"]
    # INVALID 运行无 mock 记录 → 不调 save_tool_calls
    assert names[6:10] == ["create_run", "save_context_build", "save_evaluation", "complete_run"]
    # 报告工件登记一次 + 批次收尾 COMPLETE
    assert "save_artifact" in names
    complete_batch = fake.calls[-1][1]
    assert complete_batch["status"] == "COMPLETE"
    artifact_file = tmp_path / f"session-cross/{result['batch_id']}/cross-report.json"
    assert artifact_file.read_text(encoding="utf-8") == "{}"
    assert set(result["run_ids"]) == {r["run_key"] for r in plan["runs"]}


def test_persist_plan_failure_propagates_clearly() -> None:
    artifacts = _artifacts()
    plan = build_run_persist_plan(_report(), artifacts=artifacts, items=_items(),
                                  tokenizer_version="conservative-cjk1-latin4-v1")
    fake = FakeDataClient(fail_on="create_batch")
    with pytest.raises(DataServiceError, match="injected failure"):
        persist_plan(fake, plan, report_json="{}")


def test_persist_session_cross_report_end_to_end(tmp_path: Path) -> None:
    session = load_session(_CASE_DIR / "ctx-session-touchstone-design-01.session.json")
    artifacts = _artifacts()
    fake = FakeDataClient()
    result = persist_session_cross_report(
        fake, _report(), artifacts=artifacts, session=session,
        tokenizer_version="conservative-cjk1-latin4-v1", artifacts_dir=tmp_path,
    )
    assert result["batch_id"].startswith("batch-")
    assert len(result["run_ids"]) == 2


# ── 发布器 ────────────────────────────────────────────────────────────────


def blob_keys(payload: Any) -> set[str]:
    """递归收集 JSON 结构里的全部键名(检查评测标注字段是否泄漏)。"""

    keys: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            keys.add(key)
            keys |= blob_keys(value)
    elif isinstance(payload, list):
        for row in payload:
            keys |= blob_keys(row)
    return keys


def _compile_report() -> dict[str, Any]:
    session = load_session(_CASE_DIR / "ctx-session-touchstone-design-01.session.json")
    variants = load_variants(_CASE_DIR / "ctx-session-touchstone-design-01.variants.json")
    compiler = SessionCompiler()
    compiled = {}
    for variant in variants["context_variants"]:
        artifact = compiler.compile(session, variant, common_rules="规则")
        payload = artifact.to_payload()
        payload["status"] = "COMPLETE"
        compiled[variant["variant_id"]] = payload
    return {
        "case_id": session.session_id,
        "case_version": session.session_version,
        "source_session_hash": session.source_hash,
        "event_count": len(session.events),
        "tokenizer_version": "conservative-cjk1-latin4-v1",
        "compiled": compiled,
        "checks": [],
        "checks_pass": True,
    }


def test_publisher_writes_all_static_artifacts_without_gold(tmp_path: Path) -> None:
    target = publish_session_cross(_CASE_DIR, _compile_report(), tmp_path)
    assert (target / "index.json").is_file()
    assert (target / "session.json").is_file()
    assert (target / "report.json").is_file()
    assert (target / "report.md").is_file()
    assert sorted(p.name for p in (target / "compiled").iterdir()) == [
        "budgeted-session.json", "full-session.json", "recent-window.json", "single-summary.json",
    ]
    index = json.loads((target / "index.json").read_text(encoding="utf-8"))
    assert index["event_count"] == 102
    assert len(index["variants"]) == 4
    assert len(index["matrix"]) == 12
    timeline = json.loads((target / "session.json").read_text(encoding="utf-8"))
    assert len(timeline["events"]) == 102
    # session.json 无评测标注字段(白名单键;正文自然语言不含结构化标注)
    allowed_keys = {"seq", "event_id", "occurred_at", "type", "content", "role",
                    "tool_name", "call_id", "status", "error_code"}
    assert all(set(event) <= allowed_keys for event in timeline["events"])
    assert "classification" not in blob_keys(timeline)
    assert "priority" not in blob_keys(timeline)
    # report.json 未跑实验时为 not_run 占位
    report = json.loads((target / "report.json").read_text(encoding="utf-8"))
    assert report == {"status": "not_run"}


def test_publisher_with_report_includes_drilldown(tmp_path: Path) -> None:
    target = publish_session_cross(_CASE_DIR, _compile_report(), tmp_path,
                                   report=_report(), markdown="# 报告\n内容")
    report = json.loads((target / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "run"
    assert report["cells"][0]["runs"][0]["mock_records"][0]["simulated"] is True
    assert (target / "report.md").read_text(encoding="utf-8").startswith("# 报告")


def test_publisher_is_overwrite_snapshot(tmp_path: Path) -> None:
    publish_session_cross(_CASE_DIR, _compile_report(), tmp_path)
    stale = tmp_path / "compiled" / "stale-variant.json"
    stale.write_text("{}", encoding="utf-8")
    publish_session_cross(_CASE_DIR, _compile_report(), tmp_path)
    assert not stale.exists()  # 覆盖式快照:旧文件清理
