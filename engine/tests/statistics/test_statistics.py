"""统计模块测试(P0-7 / 方案 15.7):全部使用静态运行记录,不访问任何模型服务。

覆盖:样本量分级、排除原因、确定性哈希、指标诚实缺席、快照落盘往返;
v2 追加:预期配置哈希、统一计数、数据质量警告、comparison 可用性、
formal_min 分级与兼容口径(统计模块修复方案 §11 清单)。
"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.statistics import (
    EXCLUDE_CONFIG_MISMATCH,
    EXCLUDE_DUPLICATE_RUN_ID,
    EXCLUDE_EMPTY_CONFIG_HASH,
    EXCLUDE_INVALID,
    EXCLUDE_LLM_UNAVAILABLE,
    EXCLUDE_MISSING_FIELDS,
    EXCLUDE_NO_AGENT_LOOP,
    EXCLUDE_UNKNOWN_VARIANT,
    SAMPLE_LEVEL_EXTENDED,
    SAMPLE_LEVEL_FORMAL,
    SAMPLE_LEVEL_NONE,
    SAMPLE_LEVEL_SINGLE,
    SAMPLE_LEVEL_TREND,
    STATISTICS_VERSION,
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
    snapshot = build_series_statistics("series-1", runs=runs, expected_config_hashes={"t0.1": "cfg-A", "t0.7": "cfg-A"})
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


# ── v2:身份与去重(修复方案 P0-1) ─────────────────────────────────────────


def test_duplicate_run_id_included_once():
    """同一 run_id 输入两次只纳入一次;不同 run_id 的样本全部纳入。"""
    runs = [make_run("dup-1", "t0.1"), make_run("dup-1", "t0.1", repeat=2), make_run("dup-2", "t0.1", repeat=3)]
    snapshot = build_series_statistics("s", runs=runs)
    assert snapshot.by_variant["t0.1"]["included_run_ids"] == ["dup-1", "dup-2"]
    assert reasons_of(snapshot, "dup-1") == [EXCLUDE_DUPLICATE_RUN_ID]
    assert snapshot.input_run_count == 3
    assert snapshot.included_run_count == 2
    assert snapshot.excluded_run_count == 1
    assert snapshot.included_run_count + snapshot.excluded_run_count == snapshot.input_run_count


def test_duplicate_run_id_quality_warning():
    """重复 ID 不再隐藏在排除表中:统计摘要给出数据质量警告,只陈述事实。"""
    # planned 变体 formal_min=3:dup 排除 2 条后纳入 1 条
    runs = [
        make_run("dup-1", "t0.1"),
        make_run("dup-1", "t0.1", repeat=2),
        make_run("dup-1", "t0.1", repeat=3),
        make_run("x-1", "t0.7", config="cfg-X"),
        make_run("x-2", "t0.7", repeat=2, config="cfg-X"),
        make_run("x-3", "t0.7", repeat=3, config="cfg-X"),
    ]
    snapshot = build_series_statistics(
        "s",
        runs=runs,
        planned_variants=["t0.1", "t0.7"],
        formal_min_repeat_count=3,
        expected_config_hashes={"t0.1": "cfg-A", "t0.7": "cfg-X"},
    )
    warnings = snapshot.data_quality_warnings
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning["code"] == "DUPLICATE_RUN_IDS_DETECTED"
    assert warning["severity"] == "error"
    assert warning["variant_id"] == "t0.1"
    assert warning["excluded_count"] == 2
    # 只陈述事实:无法判断重复上报还是不同物理样本,不输出因果结论
    assert "无法判断是否为同一运行重复上报" in warning["message"]
    assert "blocks_formal_min" not in warning
    assert "门槛因此无法满足" not in warning["message"]
    # 对照变体不受影响:3 个独立样本达到正式门槛
    assert snapshot.by_variant["t0.7"]["sample_level"]["level"] == SAMPLE_LEVEL_FORMAL
    # 完成计数按唯一运行身份:t0.1 的 3 行输入 = 1 个唯一身份 + 2 条重复
    assert snapshot.by_variant["t0.1"]["completed_count"] == 1
    assert snapshot.by_variant["t0.1"]["excluded_count"] == 2
    assert snapshot.input_run_count == 6
    assert snapshot.included_run_count + snapshot.excluded_run_count == snapshot.input_run_count


def test_duplicate_warning_without_causal_conclusion():
    """警告只描述重复事实,不推断"门槛因此无法满足"的因果。"""
    runs = [
        make_run("dup-1", "t0.1"),
        make_run("dup-1", "t0.1", repeat=2),
    ]
    snapshot = build_series_statistics("s", runs=runs, planned_variants=["t0.1"], formal_min_repeat_count=3)
    message = snapshot.data_quality_warnings[0]["message"]
    assert "重复 run_id" in message
    assert "门槛因此无法满足" not in message
    assert "不同样本" not in message


# ── v2:有效性、变体归属与配置一致性(修复方案 §3/§4) ─────────────────────


def test_validity_and_membership_exclusions():
    """INVALID / 无 Agent 循环 / 未知变体按固定顺序得到单一主因。"""
    runs = [
        make_run("bad", "t0.1", validity="INVALID", error="评测失败"),
        make_run("loop", "t0.1", repeat=2, steps=0),
        make_run("ghost", "t9.9", repeat=1),
    ]
    snapshot = build_series_statistics("s", runs=runs, planned_variants=["t0.1", "t0.7"])
    assert reasons_of(snapshot, "bad") == [EXCLUDE_INVALID]
    assert reasons_of(snapshot, "loop") == [EXCLUDE_NO_AGENT_LOOP]
    assert reasons_of(snapshot, "ghost") == [EXCLUDE_UNKNOWN_VARIANT]
    # 未知变体不进入 by_variant;计划内零样本变体保留 no-data
    assert "t9.9" not in snapshot.by_variant
    assert snapshot.by_variant["t0.7"]["sample_level"]["level"] == SAMPLE_LEVEL_NONE
    # 计划外变体不提供时(批次口径)不做归属检查,ghost 正常纳入
    batch_snapshot = build_series_statistics("s", runs=[make_run("ghost", "t9.9")])
    assert batch_snapshot.by_variant["t9.9"]["included_run_ids"] == ["ghost"]


def test_empty_config_hash_excluded_and_never_dominant():
    """正式统计不接受空 config_hash;空值永不成为主导值。"""
    runs = [
        make_run("empty-1", "t0.1", config=""),
        make_run("empty-2", "t0.1", repeat=2, config=""),
        make_run("solid", "t0.1", repeat=3, config="cfg-A"),
    ]
    snapshot = build_series_statistics("s", runs=runs)
    assert reasons_of(snapshot, "empty-1") == [EXCLUDE_EMPTY_CONFIG_HASH]
    assert reasons_of(snapshot, "empty-2") == [EXCLUDE_EMPTY_CONFIG_HASH]
    assert snapshot.by_variant["t0.1"]["included_run_ids"] == ["solid"]


def test_expected_config_hash_mismatch_excluded_with_detail():
    """冻结预期哈希时直接比较:不符者排除并给出 expected/actual 说明。"""
    expected = {"t0.1": "sha256:good"}
    runs = [
        make_run("good", "t0.1", config="sha256:good"),
        make_run("drift", "t0.1", repeat=2, config="sha256:drift"),
        make_run("blank", "t0.1", repeat=3, config=""),
    ]
    snapshot = build_series_statistics(
        "s",
        runs=runs,
        planned_variants=["t0.1"],
        formal_min_repeat_count=3,
        expected_config_hashes=expected,
    )
    assert snapshot.config_hash_mode == "expected"
    assert snapshot.expected_config_hashes == expected
    assert snapshot.by_variant["t0.1"]["included_run_ids"] == ["good"]
    assert reasons_of(snapshot, "drift") == [EXCLUDE_CONFIG_MISMATCH]
    detail = next(row["detail"] for row in snapshot.excluded_runs if row["run_id"] == "drift")
    assert "expected=sha256:good" in detail and "actual=sha256:drift" in detail
    # 预期口径下空哈希也如实标注
    assert reasons_of(snapshot, "blank") == [EXCLUDE_EMPTY_CONFIG_HASH]


def test_expected_mode_not_fooled_by_consistent_wrong_config():
    """全变体一致但错误的配置不得纳入:直接比较而非观察主导值。"""
    expected = {"t0.1": "sha256:good"}
    runs = [
        make_run("w1", "t0.1", config="sha256:wrong"),
        make_run("w2", "t0.1", repeat=2, config="sha256:wrong"),
    ]
    snapshot = build_series_statistics(
        "s",
        runs=runs,
        planned_variants=["t0.1"],
        formal_min_repeat_count=3,
        expected_config_hashes=expected,
    )
    assert snapshot.by_variant["t0.1"]["included_run_ids"] == []
    assert snapshot.by_variant["t0.1"]["excluded_count"] == 2


def test_dominant_mode_is_observed_compat():
    """未冻结预期哈希(历史兼容):主导值只在非空哈希中选取,并记录口径。"""
    runs = [
        make_run("a", "t0.1", config="cfg-A"),
        make_run("b", "t0.1", repeat=2, config="cfg-A"),
        make_run("c", "t0.1", repeat=3, config="cfg-B"),
        make_run("d", "t0.1", repeat=4, config=""),
    ]
    snapshot = build_series_statistics("s", runs=runs, planned_variants=["t0.1"])
    assert snapshot.config_hash_mode == "observed-dominant"
    assert snapshot.by_variant["t0.1"]["included_run_ids"] == ["a", "b"]
    assert reasons_of(snapshot, "c") == [EXCLUDE_CONFIG_MISMATCH]
    assert reasons_of(snapshot, "d") == [EXCLUDE_EMPTY_CONFIG_HASH]
    # 兼容口径在 notes 中如实说明
    assert any("观察主导值" in note for note in snapshot.notes)


def test_unified_counts_with_failed_runs():
    """完成数/失败数/排除数统一口径:完成含被判无效的完成运行。"""
    runs = [
        make_run("ok", "t0.1"),
        make_run("invalid-done", "t0.1", repeat=2, validity="INVALID", error="x"),
        make_run(
            "boom",
            "t0.1",
            repeat=3,
            run_outcome="failed",
            validity="INVALID",
            error="RuntimeError",
            stop_reason="RUN_FAILED",
            steps=0,
            duration=0,
        ),
    ]
    snapshot = build_series_statistics("s", runs=runs, planned_variants=["t0.1"])
    stats = snapshot.by_variant["t0.1"]
    assert stats["completed_count"] == 2  # ok + invalid-done(执行完成但无效)
    assert stats["failed_count"] == 1
    assert stats["included_count"] == 1
    assert stats["excluded_count"] == 2  # invalid-done + boom(失败运行计入排除)
    # 固定顺序:有效性检查先于 Agent 证据检查,同一条异常只有一个主因
    assert stats["exclusion_reasons"] == {"INVALID": 2}
    assert stats["included_count"] + stats["excluded_count"] == stats["completed_count"] + stats["failed_count"]


# ── v2:正式样本门槛(修复方案 §5) ─────────────────────────────────────────


def test_formal_min_one_single_sample_is_formal():
    """门槛为 1 且冻结预期哈希:1 个有效样本即达正式最小口径。"""
    runs = [make_run("only", "t0.1", config="cfg-A")]
    snapshot = build_series_statistics(
        "s",
        runs=runs,
        planned_variants=["t0.1"],
        formal_min_repeat_count=1,
        expected_config_hashes={"t0.1": "cfg-A"},
    )
    assert snapshot.by_variant["t0.1"]["sample_level"]["level"] == SAMPLE_LEVEL_FORMAL
    assert snapshot.formal_min_repeat_count == 1


def test_dominant_mode_caps_sample_level_to_observation():
    """未冻结预期哈希(兼容口径):样本量达标也只标"观察结果",不冒充正式样本。"""
    runs = [
        *[make_run(f"a-{i}", "t0.1", repeat=i + 1) for i in range(5)],
    ]
    snapshot = build_series_statistics("s", runs=runs, planned_variants=["t0.1", "t0.7"], formal_min_repeat_count=3)
    assert snapshot.config_hash_mode == "observed-dominant"
    assert snapshot.by_variant["t0.1"]["sample_level"]["level"] == "observed-compat"
    assert snapshot.by_variant["t0.1"]["sample_level"]["label"] == "观察结果(兼容口径)"
    # 样本量相同的正式口径(冻结哈希)才是正式样本
    formal = build_series_statistics(
        "s",
        runs=runs,
        planned_variants=["t0.1", "t0.7"],
        formal_min_repeat_count=3,
        expected_config_hashes={"t0.1": "cfg-A"},
    )
    assert formal.by_variant["t0.1"]["sample_level"]["level"] == SAMPLE_LEVEL_EXTENDED


def test_formal_min_three_two_samples_still_trend():
    """门槛为 3 的温度模板:两个有效样本仍是初步趋势,不显示正式结论。"""
    runs = [make_run("a", "t0.0"), make_run("b", "t0.0", repeat=2)]
    snapshot = build_series_statistics("s", runs=runs, planned_variants=["t0.0"], formal_min_repeat_count=3)
    assert snapshot.by_variant["t0.0"]["sample_level"]["level"] == SAMPLE_LEVEL_TREND


def test_overall_level_is_min_including_zero_sample_variants():
    """整体等级取所有计划变体最低值;零样本计划变体保留并显示无数据。"""
    runs = [
        *[make_run(f"a-{i}", "t0.1", repeat=i + 1) for i in range(5)],
        make_run("b-1", "t0.7"),
    ]
    snapshot = build_series_statistics(
        "s",
        runs=runs,
        planned_variants=["t0.1", "t0.7", "t0.9"],
        formal_min_repeat_count=3,
        expected_config_hashes={"t0.1": "cfg-A", "t0.7": "cfg-A"},
    )
    assert snapshot.by_variant["t0.1"]["sample_level"]["level"] == SAMPLE_LEVEL_EXTENDED
    assert snapshot.by_variant["t0.7"]["sample_level"]["level"] == SAMPLE_LEVEL_SINGLE
    assert snapshot.by_variant["t0.9"]["included_run_ids"] == []
    assert snapshot.by_variant["t0.9"]["sample_level"]["level"] == SAMPLE_LEVEL_NONE
    assert snapshot.sample_sufficiency["overall_level"] == SAMPLE_LEVEL_NONE


def test_formal_min_and_expected_hashes_change_snapshot_hash():
    """改变正式门槛或预期配置哈希会改变快照哈希(定义进入派生指纹)。"""
    runs = [make_run("a", "t0.1", config="cfg-A"), make_run("b", "t0.1", repeat=2, config="cfg-A")]
    base = build_series_statistics("s", runs=runs, planned_variants=["t0.1"], formal_min_repeat_count=3)
    stricter = build_series_statistics("s", runs=runs, planned_variants=["t0.1"], formal_min_repeat_count=5)
    with_expected = build_series_statistics(
        "s",
        runs=runs,
        planned_variants=["t0.1"],
        formal_min_repeat_count=3,
        expected_config_hashes={"t0.1": "cfg-A"},
    )
    assert base.snapshot_hash != stricter.snapshot_hash
    assert base.snapshot_hash != with_expected.snapshot_hash
    assert (
        base.snapshot_hash
        == build_series_statistics("s", runs=runs, planned_variants=["t0.1"], formal_min_repeat_count=3).snapshot_hash
    )


# ── v2:comparison 可用性(修复方案 §6.3) ──────────────────────────────────


def test_comparison_unavailable_with_zero_sample_planned_variants():
    """计划变体即使零样本也存在于 by_variant,不能用 bool(by_variant) 判断。"""
    snapshot = build_series_statistics("s", runs=[], planned_variants=["t0.1", "t0.7"], formal_min_repeat_count=3)
    assert snapshot.by_variant  # 零样本变体在结果中
    assert snapshot.comparison["available"] is False
    assert snapshot.comparison["formal_available"] is False
    assert snapshot.comparison["reason"] == "至少两个变体需要有效样本"


def test_comparison_preliminary_vs_formal():
    runs = [make_run("a", "t0.1"), make_run("b", "t0.7")]
    snapshot = build_series_statistics("s", runs=runs, planned_variants=["t0.1", "t0.7"], formal_min_repeat_count=3)
    assert snapshot.comparison["available"] is True
    assert snapshot.comparison["formal_available"] is False
    assert snapshot.comparison["reason"] == "部分变体尚未达到正式最小样本"

    formal_runs = [
        *[make_run(f"a-{i}", "t0.1", repeat=i + 1) for i in range(3)],
        *[make_run(f"b-{i}", "t0.7", repeat=i + 1) for i in range(3)],
    ]
    formal = build_series_statistics(
        "s",
        runs=formal_runs,
        planned_variants=["t0.1", "t0.7"],
        formal_min_repeat_count=3,
        expected_config_hashes={"t0.1": "cfg-A", "t0.7": "cfg-A"},
    )
    assert formal.comparison["available"] is True
    assert formal.comparison["formal_available"] is True
    assert formal.comparison["reason"] == ""


def test_comparison_dominant_mode_never_formal():
    """未冻结预期哈希时正式对比不可用(修复方案 P1-2),无论样本量多大。"""
    formal_runs = [
        *[make_run(f"a-{i}", "t0.1", repeat=i + 1) for i in range(5)],
        *[make_run(f"b-{i}", "t0.7", repeat=i + 1) for i in range(5)],
    ]
    snapshot = build_series_statistics(
        "s", runs=formal_runs, planned_variants=["t0.1", "t0.7"], formal_min_repeat_count=3
    )
    assert snapshot.comparison["available"] is True
    assert snapshot.comparison["formal_available"] is False
    assert snapshot.comparison["reason"] == "未冻结预期配置哈希(观察主导值兼容口径),不作为正式对比"


def test_comparison_single_planned_variant():
    snapshot = build_series_statistics("s", runs=[make_run("a", "t0.1")], planned_variants=["t0.1"])
    assert snapshot.comparison["available"] is False
    assert snapshot.comparison["reason"] == "计划变体不足两个,无法对比"


# ── v2:确定性与版本 ───────────────────────────────────────────────────────


def test_input_order_does_not_change_snapshot():
    """调换输入运行顺序不改变快照哈希与统计结果(方案 §11 确定性)。"""
    runs = [
        make_run("a", "t0.1", task_success=True),
        make_run("b", "t0.1", repeat=2, task_success=False),
        make_run("c", "t0.7", config="cfg-B"),
    ]
    forward = build_series_statistics("s", runs=runs, generated_at="2026-08-29T00:00:00+00:00")
    backward = build_series_statistics("s", runs=list(reversed(runs)), generated_at="2026-08-29T00:00:00+00:00")
    assert forward.snapshot_hash == backward.snapshot_hash
    assert forward.to_payload() == backward.to_payload()


def test_statistics_version_is_v2():
    snapshot = build_series_statistics("s", runs=[])
    assert snapshot.statistics_version == STATISTICS_VERSION
    assert STATISTICS_VERSION == "experiment-stats-v2"
