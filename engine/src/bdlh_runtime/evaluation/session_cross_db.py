"""Session 交叉验证的数据库落库(经 data 服务,不直连库)。

完全复用既有表与接口(batch/run/context_build/tool_calls/evaluation/
complete),不新建表、不改 Java 端。契约口径:

- ``experimentType`` 自由文本(仅 @NotBlank),本实验用 ``session-cross``;
- ``agentMode`` 自由 VARCHAR(50),直接用 ``baseline-tool-calling`` /
  ``langgraph-react`` / ``full-system``(与 run_telemetry 口径一致),
  原始模式名同时保留在 modelConfig;
- 工具调用字段名是 ``sequence``/``fixtureHit``(无 fixtureId 列),
  fixture_id 与 simulated 标记放进 resultSummary;
- 重复运行 --save-db 生成新批次(agent_runs 无同参唯一约束,批次不可变)。

隔离红线:落库内容不含 gold 文件原文;judgment 里的 missing_constraints /
superseded_misuse 等结论性字段是评测输出,可以入库。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from bdlh_runtime.data_client import DataClient
from bdlh_runtime.evaluation.run_telemetry import context_build_payload
from bdlh_runtime.session import CompiledContext, SessionCase
from bdlh_runtime.session.compiler import STRUCTURED_TEXT_ALGO_VERSION

#: data 服务 create_batch 的 experimentType(自由文本,区分 agent-implementation)
SESSION_CROSS_EXPERIMENT_TYPE = "session-cross"

_SENSITIVE_KEYS = {"apikey", "api_key", "llm_api_key", "password", "token", "secret"}


def _canonical_hash(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def build_batch_payload(report: dict[str, Any], *, name: str) -> dict[str, Any]:
    fixed = dict(report.get("frozen_conditions") or {})
    fixed.update(
        {
            "evaluator_version": report.get("evaluator_version"),
            "git_commit": report.get("git_commit"),
            "model": report.get("model"),
            "runs_per_cell": report.get("runs_per_cell"),
        }
    )
    return {
        "name": name,
        "experimentType": SESSION_CROSS_EXPERIMENT_TYPE,
        "fixedConditions": fixed,
    }


def _tool_status(status: str | None) -> str:
    return {"success": "SUCCESS", "error": "FAILED"}.get(str(status or "").lower(), "INVALID")


def build_tool_calls_payload(run: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for record in run.get("mock_records") or []:
        arguments = dict(record.get("arguments") or {})
        calls.append(
            {
                "sequence": int(record.get("step") or 0),
                "toolName": str(record.get("tool_name") or ""),
                "arguments": arguments,
                "argumentsHash": _canonical_hash(arguments),
                "status": _tool_status(record.get("status")),
                "durationMs": 0,  # 冻结 Mock:无真实延迟可记
                "resultSummary": {
                    "fixture_id": record.get("fixture_id"),
                    "result": record.get("result") or {},
                    "simulated": bool(record.get("simulated", True)),
                },
                "fixtureHit": record.get("fixture_id") is not None,
            }
        )
    calls.sort(key=lambda row: row["sequence"])
    return calls


def build_context_build_payload(
    artifact: CompiledContext, items: list[Any], *, tokenizer_version: str
) -> dict[str, Any]:
    assert artifact.build_result is not None  # 冻结工件携带底层构建结果
    return context_build_payload(
        artifact.build_result,
        items,
        duration_ms=artifact.build_duration_ms,
        tokenizer_version=tokenizer_version,
        compression_version=artifact.scoring_version or STRUCTURED_TEXT_ALGO_VERSION,
    )


def build_run_persist_plan(
    report: dict[str, Any],
    *,
    artifacts: dict[str, CompiledContext],
    items: list[Any],
    tokenizer_version: str,
    fixture_set_id: str | None = None,
) -> dict[str, Any]:
    """构造整份落库计划:1 个批次 + 每格每次运行的载荷序列 + 报告工件登记。"""

    batch = build_batch_payload(
        report, name=f"session-cross-{report.get('case_id')}-{report.get('generated_date') or 'undated'}"
    )
    runs: list[dict[str, Any]] = []
    for cell in report.get("cells") or []:
        variant_id = str(cell.get("context_variant"))
        mode = str(cell.get("agent_mode"))
        artifact = artifacts.get(variant_id)
        for run in cell.get("runs") or []:
            judgment = dict(run.get("judgment") or {})
            valid = run.get("validity") == "VALID"
            error = run.get("error")
            plan = {
                "create_run": {
                    "batchId": None,  # 占位,持久化时填入
                    "caseId": report.get("case_id"),
                    "caseVersion": report.get("case_version"),
                    "variantId": variant_id,
                    "snapshotId": fixture_set_id,
                    "agentMode": mode,
                    "contextStrategy": artifact.strategy if artifact else variant_id,
                    "model": report.get("model"),
                    "gitCommit": report.get("git_commit"),
                    "modelConfig": {
                        "repeatIndex": run.get("repeat_index"),
                        "run_key": run.get("run_key"),
                        "original_agent_mode": mode,
                        "toolData": "frozen-mock",
                        "tokenizer_version": tokenizer_version,
                        "budgeted_scoring": (report.get("frozen_conditions") or {}).get("budgeted_scoring"),
                        "llm_summary": (report.get("frozen_conditions") or {}).get("llm_summary"),
                        "agentModeMapping": "baseline-tool-calling/langgraph-react/full-system 直接落库,无映射",
                    },
                },
                "tool_calls": build_tool_calls_payload(run),
                "evaluation": {
                    "evaluatorVersion": str(report.get("evaluator_version") or "session-cross-eval-v1"),
                    "validRun": valid,
                    "status": "COMPLETE" if valid else "INVALID",
                    "checks": judgment,
                    "metrics": {
                        "duration_ms": run.get("duration_ms"),
                        "tool_selection_rate": (judgment.get("tool_plan") or {}).get("selection_rate"),
                        "constraint_retention": judgment.get("constraint_retention"),
                    },
                },
                "complete": {
                    "status": "COMPLETE" if valid else "INVALID",
                    "output": {
                        "answer_excerpt": str(run.get("answer") or "")[:200],
                        "error": error,
                        "run_key": run.get("run_key"),
                        "error_category": judgment.get("error_category"),
                    },
                    "errorCategory": judgment.get("error_category"),
                    "errorMessage": str(error) if error else None,
                },
            }
            if artifact is not None:
                plan["context_build"] = build_context_build_payload(
                    artifact, items, tokenizer_version=tokenizer_version
                )
            runs.append({"run_key": run.get("run_key"), "payloads": plan})
    return {
        "batch": batch,
        "runs": runs,
        "report_artifact": {
            "artifactType": "session_cross_report",
            "storageRef": "",  # 持久化时写入文件后回填
            "contentHash": _canonical_hash(report),
            "public": False,
        },
    }


def sanitize_for_print(payload: Any) -> Any:
    """打印前脱敏:移除密钥类字段(载荷本不含,防御性兜底)。"""

    if isinstance(payload, dict):
        return {
            key: ("***redacted***" if str(key).lower() in _SENSITIVE_KEYS else sanitize_for_print(value))
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [sanitize_for_print(row) for row in payload]
    return payload


def persist_plan(
    data: DataClient,
    plan: dict[str, Any],
    *,
    report_json: str,
    artifacts_dir=None,
) -> dict[str, Any]:
    """按计划落库:批次 → 逐运行(context/tool/evaluation/complete)→ 报告工件 → 批次收尾。"""

    batch_payload = plan["batch"]
    batch_id = data.create_batch(
        name=batch_payload["name"], fixed_conditions=batch_payload["fixedConditions"]
    )
    run_ids: dict[str, str] = {}
    report_run_id: str | None = None
    for entry in plan["runs"]:
        payloads = entry["payloads"]
        create = dict(payloads["create_run"])
        create["batchId"] = batch_id
        run_id = data.create_run(create)
        run_ids[str(entry["run_key"])] = run_id
        build = payloads.get("context_build")
        if build:
            data.save_context_build(run_id, build)
        if payloads["tool_calls"]:
            data.save_tool_calls(run_id, payloads["tool_calls"])
        evaluation = payloads["evaluation"]
        data.save_evaluation(
            run_id,
            checks=evaluation["checks"],
            metrics=evaluation["metrics"],
            valid_run=evaluation["validRun"],
            status=evaluation["status"],
            evaluator_version=evaluation["evaluatorVersion"],
        )
        complete = payloads["complete"]
        data.complete_run(
            run_id,
            complete["output"],
            status=complete["status"],
            error_category=complete["errorCategory"],
            error_message=complete["errorMessage"],
        )
        if report_run_id is None:
            report_run_id = run_id

    storage_ref = ""
    if artifacts_dir is not None:
        from pathlib import Path

        directory = Path(artifacts_dir)
        storage_ref = f"session-cross/{batch_id}/cross-report.json"
        report_file = directory / storage_ref
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(report_json, encoding="utf-8")
    artifact = dict(plan["report_artifact"])
    artifact["storageRef"] = storage_ref or f"session-cross/{batch_id}/cross-report.json"
    if report_run_id is not None:
        data.save_artifact(
            report_run_id,
            artifact_type=artifact["artifactType"],
            storage_ref=artifact["storageRef"],
            content_hash=artifact["contentHash"],
            public=artifact["public"],
        )
    data.complete_batch(batch_id, "COMPLETE")
    return {"batch_id": batch_id, "run_ids": run_ids}


def persist_session_cross_report(
    data: DataClient,
    report: dict[str, Any],
    *,
    artifacts: dict[str, CompiledContext],
    session: SessionCase,
    tokenizer_version: str,
    artifacts_dir=None,
) -> dict[str, Any]:
    from bdlh_runtime.context import ContextClassification, ContextItem, ContextRole
    from bdlh_runtime.session import serialize_session

    items: list[ContextItem] = [
        ContextItem(
            item_id="system-prompt",
            content="(公共系统规则,见 common_prompt_hash)",
            classification=ContextClassification.REQUIRED,
            role=ContextRole.SYSTEM,
            sequence=-1000,
        )
    ]
    items.extend(entry.item for entry in serialize_session(session))
    items.append(
        ContextItem(
            item_id="current-question",
            content=session.current_question,
            classification=ContextClassification.REQUIRED,
            role=ContextRole.USER_DATA,
            sequence=session.events[-1].seq + 1,
            conversation=True,
        )
    )
    plan = build_run_persist_plan(
        report,
        artifacts=artifacts,
        items=items,
        tokenizer_version=tokenizer_version,
        fixture_set_id=session.fixture_set_id,
    )
    report_json = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    return persist_plan(data, plan, report_json=report_json, artifacts_dir=artifacts_dir)


__all__ = [
    "SESSION_CROSS_EXPERIMENT_TYPE",
    "build_batch_payload",
    "build_run_persist_plan",
    "build_tool_calls_payload",
    "persist_plan",
    "persist_session_cross_report",
    "sanitize_for_print",
]
