"""统计模块测试(P0-7 / 方案 15.7):全部使用静态运行记录,不访问任何模型服务。

覆盖:样本量分级、排除原因、确定性哈希、指标诚实缺席、快照落盘往返。
"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.statistics import (
    EXCLUDE_CONFIG_MISMATCH,
    EXCLUDE_DUPLICATE_RUN_ID,
    EXCLUDE_LLM_UNAVAILABLE,
    EXCLUDE_MISSING_FIELDS,
    EXCLUDE_NO_AGENT_LOOP,
    SAMPLE_LEVEL_EXTENDED,
    SAMPLE_LEVEL_FORMAL,
    SAMPLE_LEVEL_NONE,
    SAMPLE_LEVEL_SINGLE,
    SAMPLE_LEVEL_TREND,
    build_series_statistics,
    build_snapshot,
    load_snapshot,
    persist_snapshot,
    sample_level_for,
)


def make_run(
    run_id: str,
    variant: str,
    repeat: int = 1,
    *,
    steps: int = 3,
    duration: int = 1000,
    config: str = "cfg-A",
    validity: str = "VALID",
    error: str | None = None,
    stop_reason: str = "COMPLETED",
    **extra: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "run_id": run_id,
        "variant_label": variant,
        "repeat_index": repeat,
        "config_hash": config,
        "validity": validity,
        "stop_reason": stop_reason,
        "actual_agent_steps": steps,
        "duration_ms": duration,
        "tool_calls": [{"name": "weather.get_forecast"}],
        "error": error,
    }
    row.update(extra)
    return row


def reasons_of(snapshot: Any, run_id: str) -> list[str]:
    return [row["reason"] for row in snapshot.excluded_runs if row["run_id"] == run_id]


def test_sample_level_progression():
    """1/2/3/5 个样本时结果等级正确变化(方案 13.9 分级表)。"""
    assert sample_level_for(0)["level"] == SAMPLE_LEVEL_NONE
    assert sample_level_for(1)["level"] == SAMPLE_LEVEL_SINGLE
    assert sample_level_for(2)["level"] == SAMPLE_LEVEL_TREND
    assert sample_level_for(3)["level"] == SAMPLE_LEVEL_FORMAL
    assert sample_level_for(4)["level"] == SAMPLE_LEVEL_FORMAL
    assert sample_level_for(5)["level"] == SAMPLE_LEVEL_EXTENDED


def test_levels_from_runs_per_variant():
    runs = [
        *[make_run(f"lo-{i}", "t0.1", repeat=1) for i in range(3)],
        *[make_run(f"hi-{i}", "t0.7", repeat=1) for i in range(5)],
    ]
    snapshot = build_series_statistics("series-1", runs=runs)
    assert snapshot.by_variant["t0.1"]["sample_level"]["level"] == SAMPLE_LEVEL_FORMAL
    assert snapshot.by_variant["t0.7"]["sample_level"]["level"] == SAMPLE_LEVEL_EXTENDED
    assert snapshot.sample_sufficiency["overall_level"] == SAMPLE_LEVEL_FORMAL


def test_exclusion_reasons():
    runs = [
        make_run("ok-1", "t0.1"),
        make_run("bad-llm", "t0.1", repeat=2, validity="INVALID", error="LLM_UNAVAILABLE: api key 未配置"),
        make_run("no-loop", "t0.1", repeat=3, steps=0, duration=0),
        make_run("missing", "", repeat=1),
        make_run("dup", "t0.7"),
        make_run("dup", "t0.7", repeat=2),
        make_run("cfg-b", "t0.7", repeat=3, config="cfg-B"),
    ]
    snapshot = build_series_statistics("series-1", runs=runs)
    assert reasons_of(snapshot, "bad-llm") == [EXCLUDE_LLM_UNAVAILABLE]
    assert reasons_of(snapshot, "no-loop") == [EXCLUDE_NO_AGENT_LOOP]
    assert reasons_of(snapshot, "missing") == [EXCLUDE_MISSING_FIELDS]
    assert reasons_of(snapshot, "dup") == [EXCLUDE_DUPLICATE_RUN_ID]
    assert reasons_of(snapshot, "cfg-b") == [EXCLUDE_CONFIG_MISMATCH]
    # 有效运行:t0.1 只剩 ok-1;t0.7 剩 1 个 cfg-A + cfg-b 被排除
    assert snapshot.by_variant["t0.1"]["included_run_ids"] == ["ok-1"]
    assert snapshot.by_variant["t0.7"]["included_run_ids"] == ["dup"]
    assert snapshot.by_variant["t0.1"]["excluded_count"] == 2  # bad-llm + no-loop
    # 同一 run_id 只出现在 included 中一次
    assert len(snapshot.included_run_ids) == len(set(snapshot.included_run_ids))


def test_metrics_and_honest_absence():
    runs = [
        make_run("a", "t0.1", repeat=1, steps=1, duration=100),
        make_run("b", "t0.1", repeat=2, steps=2, duration=300),
        make_run("c", "t0.1", repeat=3, steps=3, duration=500),
    ]
    snapshot = build_series_statistics("series-1", runs=runs)
    stats = snapshot.by_variant["t0.1"]
    assert stats["actual_agent_steps"] == {"mean": 2.0, "median": 2.0, "min": 1, "max": 3, "n": 3}
    assert stats["duration_ms"] == {"mean": 300.0, "median": 300.0, "min": 100, "max": 500, "n": 3}
    assert stats["tool_calls_per_run"]["mean"] == 1.0
    assert stats["stop_reasons"] == {"COMPLETED": 3}
    assert stats["success_rate"] is None
    assert stats["input_tokens"] is None
    assert stats["output_tokens"] is None
    # 未持久化的指标如实缺席,并在 notes 中说明
    assert any("Token" in note for note in snapshot.notes)
    assert any("task_success" in note for note in snapshot.notes)


def test_future_fields_computed_when_present():
    """运行记录未来补充计量字段后,统计自动覆盖,无需改统计模块。"""
    runs = [
        make_run("a", "t0.1", task_success=True, input_tokens=100, output_tokens=50),
        make_run("b", "t0.1", repeat=2, task_success=False, input_tokens=200, output_tokens=150),
    ]
    snapshot = build_series_statistics("series-1", runs=runs)
    stats = snapshot.by_variant["t0.1"]
    assert stats["success_rate"] == 0.5
    assert stats["input_tokens"]["median"] == 150.0
    assert stats["output_tokens"]["mean"] == 100.0
    assert not any("Token" in note for note in snapshot.notes)
    assert not any("task_success" in note for note in snapshot.notes)


def test_deterministic_hash_rebuild():
    """同一批运行记录重算任意次,除 generated_at 外逐字节一致(方案 13.10 可重建)。"""
    runs = [make_run("a", "t0.1"), make_run("b", "t0.1", repeat=2), make_run("c", "t0.7")]
    first = build_series_statistics("s", runs=runs, generated_at="2026-08-28T00:00:00+00:00")
    second = build_series_statistics("s", runs=runs, generated_at="2026-08-28T12:00:00+00:00")
    assert first.snapshot_hash == second.snapshot_hash
    assert first.generated_at != second.generated_at
    left = first.to_payload()
    right = second.to_payload()
    left.pop("generated_at")
    right.pop("generated_at")
    assert left == right


def test_definition_hash_from_report():
    report = {
        "template_id": "temperature-stability",
        "template_version": 1,
        "fixed_conditions_hash": "sha256:abc",
        "runs": [make_run("a", "t0.0")],
    }
    snapshot = build_series_statistics("s", report=report)
    assert snapshot.template_id == "temperature-stability"
    assert snapshot.definition_hash == "sha256:abc"


def test_empty_report_is_no_data():
    snapshot = build_snapshot("s", report={})
    assert snapshot["by_variant"] == {}
    assert snapshot["sample_sufficiency"]["overall_level"] == SAMPLE_LEVEL_NONE
    assert snapshot["notes"]
    assert snapshot["included_run_ids"] == []


def test_snapshot_roundtrip(tmp_path):
    report = {"template_id": "t", "runs": [make_run("a", "t0.1"), make_run("b", "t0.7")]}
    payload = build_snapshot("series/x:1", report=report)
    path = persist_snapshot(payload, root=tmp_path)
    assert path.is_file()
    assert load_snapshot("series/x:1", root=tmp_path) == payload
    assert load_snapshot("nonexistent", root=tmp_path) is None
