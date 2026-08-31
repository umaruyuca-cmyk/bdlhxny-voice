"""旧批次迁移测试(方案 13.13 第 1–4 条):静态报告,不访问模型服务,不重跑任何 Agent。"""

from __future__ import annotations

import json
from typing import Any

from bdlh_runtime.experiments.series_migrate import (
    iter_artifact_batch_ids,
    load_report,
    main,
    migrate_all,
    migrate_batch,
    runs_from_legacy_report,
)
from bdlh_runtime.experiments.series_store import SeriesStore
from bdlh_runtime.statistics.service import load_snapshot


def _run(run_id: str, variant: str, repeat: int, *, validity: str = "VALID") -> dict[str, Any]:
    return {
        "run_id": run_id,
        "variant_label": variant,
        "repeat_index": repeat,
        "config_hash": "cfg-A",
        "validity": validity,
        "stop_reason": "COMPLETED",
        "actual_agent_steps": 2,
        "duration_ms": 500,
        "tool_calls": [],
        "error": None,
    }


def _template_report(**overrides: Any) -> dict[str, Any]:
    report: dict[str, Any] = {
        "template_id": "temperature-stability",
        "template_version": 1,
        "fixed_conditions": {"case_id": "cmp-x"},
        "fixed_conditions_hash": "sha256:fixed",
        "runs": [_run("r-a-0", "t0.1", 0), _run("r-a-1", "t0.1", 1)],
    }
    report.update(overrides)
    return report


def test_migrate_template_report(tmp_path):
    store = SeriesStore(root=tmp_path / "series")
    result = migrate_batch("batch-m1", _template_report(), store=store, statistics_root=tmp_path / "stats")
    assert result["status"] == "migrated"
    assert result["migrated_runs"] == 2
    record = store.get("batch-m1")
    assert record is not None
    assert record.series_id == "batch-m1"  # 13.13 第 1 条:batch_id 保留为 series_id
    assert record.template_id == "temperature-stability"
    assert record.formal_min_repeat_count == 3  # 来自模板注册表
    assert record.variant_labels == ["t0.1"]
    assert [entry["repeat_index"] for entry in record.runs] == [1, 2]  # 存储口径:第 1 次起
    assert all(entry["status"] == "done" for entry in record.runs)
    assert all(entry["payload"]["run_id"] for entry in record.runs)  # 原样保留,不改写历史

    snapshot = load_snapshot("batch-m1", root=tmp_path / "stats")
    assert snapshot is not None
    assert len(snapshot["included_run_ids"]) == 2
    assert snapshot["snapshot_hash"] == result["snapshot_hash"]
    assert snapshot["by_variant"]["t0.1"]["sample_level"]["level"] == "preliminary-trend"  # 2 样本=初步趋势


def test_migrate_is_idempotent(tmp_path):
    store = SeriesStore(root=tmp_path / "series")
    first = migrate_batch("batch-m2", _template_report(), store=store, statistics_root=tmp_path / "stats")
    assert first["status"] == "migrated"
    second = migrate_batch("batch-m2", _template_report(), store=store, statistics_root=tmp_path / "stats")
    assert second["status"] == "skipped"
    assert "已存在" in second["reason"]
    assert store.get("batch-m2").runs[0]["payload"]["run_id"] == "r-a-0"  # 原记录未被改写


def test_migrate_force_overwrites(tmp_path):
    store = SeriesStore(root=tmp_path / "series")
    migrate_batch("batch-m3", _template_report(), store=store, statistics_root=tmp_path / "stats")
    bigger = _template_report(runs=[_run("r-a-0", "t0.1", 0), _run("r-a-1", "t0.1", 1), _run("r-b-0", "t0.7", 0)])
    result = migrate_batch("batch-m3", bigger, store=store, statistics_root=tmp_path / "stats", force=True)
    assert result["status"] == "migrated"
    assert result["migrated_runs"] == 3
    assert store.get("batch-m3").variant_labels == ["t0.1", "t0.7"]


def test_migrate_dedupes_variant_repeat(tmp_path):
    """(variant_id, repeat_index) 唯一键:重复运行跳过并计数,不重复统计。"""
    store = SeriesStore(root=tmp_path / "series")
    duplicated = _template_report(
        runs=[_run("r-a-0", "t0.1", 0), _run("r-a-0-dup", "t0.1", 0), _run("r-a-1", "t0.1", 1)]
    )
    result = migrate_batch("batch-m4", duplicated, store=store, statistics_root=tmp_path / "stats")
    assert result["status"] == "migrated"
    assert result["migrated_runs"] == 2
    assert result["duplicates"] == 1
    assert any("去重" in note for note in result["notes"])


def test_migrate_maps_compression_cells(tmp_path):
    """压缩对照旧格式(cells)映射为独立 Run;template_id 从实验定义推断。"""
    store = SeriesStore(root=tmp_path / "series")
    report = {
        "test_type": "COMPRESSION_CASE",
        "session_id": "ctx-session-context-engine-debug-01",
        "fixed_conditions": {
            "experiment_definition": "compression-method-comparison",
            "session_id": "ctx-session-context-engine-debug-01",
        },
        "fixed_conditions_hash": "sha256:cmp",
        "cells": [
            {
                "unit_id": "s1:budgeted:native",
                "context_variant": "budgeted",
                "repeat_index": 0,
                "config_hash": "cfg-b",
                "validity": "VALID",
                "stop_reason": "FINAL_ANSWER",
                "actual_agent_steps": 3,
                "duration_ms": 700,
                "tool_calls": [],
                "error": None,
                "answer": "ok",
            },
            {
                "unit_id": "s1:budgeted-llm:native",
                "context_variant": "budgeted-llm",
                "repeat_index": 0,
                "config_hash": "cfg-c",
                "validity": "INVALID",
                "stop_reason": "ERROR",
                "actual_agent_steps": 0,
                "duration_ms": 0,
                "tool_calls": [],
                "error": "LLM_UNAVAILABLE",
                "answer": "",
            },
        ],
    }
    result = migrate_batch("batch-c1", report, store=store, statistics_root=tmp_path / "stats")
    assert result["status"] == "migrated"
    assert result["migrated_runs"] == 2
    assert any("cells" in note for note in result["notes"])
    record = store.get("batch-c1")
    assert record.template_id == "compression-method-comparison"
    assert record.case_id == "ctx-session-context-engine-debug-01"
    assert [entry["variant_id"] for entry in record.runs] == ["budgeted", "budgeted-llm"]
    # 无效运行原样迁移,由统计口径排除(不静默删除历史)
    snapshot = load_snapshot("batch-c1", root=tmp_path / "stats")
    assert snapshot["included_run_ids"] == ["s1:budgeted:native"]
    assert snapshot["excluded_runs"][0]["reason"] == "LLM_UNAVAILABLE"


def test_migrate_skips_non_template_artifact(tmp_path):
    """更早期的 eval 工件(无 template_id/runs)如实跳过,不误迁。"""
    store = SeriesStore(root=tmp_path / "series")
    legacy = {"cases": [{"case_id": "x"}], "groups": [], "run_records": []}
    result = migrate_batch("batch-old", legacy, store=store, statistics_root=tmp_path / "stats")
    assert result["status"] == "skipped"
    assert "非模板" in result["reason"]
    assert store.get("batch-old") is None


def test_runs_from_legacy_report_prefers_runs():
    mapped, notes = runs_from_legacy_report(_template_report())
    assert len(mapped) == 2
    assert notes == []


def test_migrate_all_scans_artifacts_and_prefers_data(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "batch-ok.json").write_text(json.dumps(_template_report()), encoding="utf-8")
    (artifacts / "batch-legacy.json").write_text(json.dumps({"cases": []}), encoding="utf-8")
    store = SeriesStore(root=tmp_path / "series")
    results = migrate_all(store=store, artifacts_root=artifacts, statistics_root=tmp_path / "stats")
    by_id = {row["batch_id"]: row for row in results}
    assert by_id["batch-ok"]["status"] == "migrated"
    assert by_id["batch-legacy"]["status"] == "skipped"
    assert iter_artifact_batch_ids(artifacts) == ["batch-legacy", "batch-ok"]

    # data_loader 优先:库里有报告时以库为准;loader 抛错回退本地工件
    calls: list[str] = []

    def loader(batch_id: str):
        calls.append(batch_id)
        if batch_id == "batch-ok":
            raise RuntimeError("data 不可达")
        return _template_report(runs=[_run("r-db-0", "t0.1", 0)])

    store2 = SeriesStore(root=tmp_path / "series2")
    results2 = migrate_all(
        store=store2,
        artifacts_root=artifacts,
        data_loader=loader,
        statistics_root=tmp_path / "stats2",
        batch_ids=["batch-ok", "batch-legacy"],
    )
    assert calls == ["batch-ok", "batch-legacy"]
    assert results2[0]["status"] == "migrated"  # 回退到本地工件成功
    assert results2[1]["status"] == "migrated"  # 来自 data_loader 的报告


def test_cli_main_smoke(tmp_path, monkeypatch, capsys):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "batch-cli.json").write_text(json.dumps(_template_report()), encoding="utf-8")
    monkeypatch.setenv("SERIES_DIR", str(tmp_path / "series"))
    monkeypatch.setenv("STATISTICS_DIR", str(tmp_path / "stats"))
    code = main(["--artifacts-dir", str(artifacts), "--batch", "batch-cli"])
    assert code == 0
    out = capsys.readouterr().out
    assert "[migrated] batch-cli" in out
    assert load_report("batch-cli", artifacts_root=artifacts)["template_id"] == "temperature-stability"
