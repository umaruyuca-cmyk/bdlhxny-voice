"""纯代码聚合(P0-7 13.8):过滤 → 归一 → 按变体汇总 → 样本分级。

设计约束(方案 13.6/13.14 与统计模块修复方案):
- 只读取入参运行记录,统计重算不产生任何 LLM 请求;
- 固定顺序处理输入(修复方案 §3.1):字段完整性 → 运行身份去重 → 有效性
  → Agent 执行证据 → 变体归属 → 配置一致性 → 指标提取 → 分组统计,
  同一条异常数据只有一个主要排除原因,重算时原因不漂移;
- 同一 run_id 只统计一次;重复 run_id 额外产生 ``data_quality_warnings``,
  不静默 hiding 在排除表中;
- 配置一致性双口径(修复方案 §4):有预期配置哈希时直接与冻结值比较
  (正式口径);无冻结值时退回观察主导值(历史兼容)。空 config_hash
  一律排除,永不成为主导值;
- 未持久化的指标(如 Token、task_success)如实缺席,不以 0 冒充。
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from statistics import median
from typing import Any

from bdlh_runtime.statistics.models import (
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
    SAMPLE_LEVEL_LABELS,
    SAMPLE_LEVEL_NONE,
    SAMPLE_LEVEL_OBSERVATION,
    SAMPLE_LEVEL_RANK,
    StatisticsSnapshot,
    VariantStatistics,
    canonical_hash,
    sample_level_for,
)
from bdlh_runtime.statistics.repository import report_meta, runs_from_report

#: error 文本中出现的失败指向(与 template_runner 的 LLM_UNAVAILABLE 标记对齐)
_FAILURE_HINT_REASONS = (EXCLUDE_LLM_UNAVAILABLE,)

#: 配置一致性口径:实验组冻结预期哈希(正式) / 观察主导值(历史兼容)
CONFIG_HASH_MODE_EXPECTED = "expected"
CONFIG_HASH_MODE_DOMINANT = "observed-dominant"

#: 数据质量警告代码(修复方案 P0-1)
WARNING_DUPLICATE_RUN_IDS = "DUPLICATE_RUN_IDS_DETECTED"


def _as_number(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _stats_block(values: list[float]) -> dict[str, Any] | None:
    if not values:
        return None
    return {
        "mean": round(sum(values) / len(values), 4),
        "median": round(float(median(values)), 4),
        "min": min(values),
        "max": max(values),
        "n": len(values),
    }


def _dominant(values: list[str]) -> str:
    """出现最多的取值;并列时取字典序最小,保证确定性。只接收非空值。"""
    counts = Counter(values)
    best = max(counts.values())
    return sorted(value for value, count in counts.items() if count == best)[0]


def _failure_reason(row: dict[str, Any]) -> str:
    error = str(row.get("error") or "")
    for hint in _FAILURE_HINT_REASONS:
        if hint in error:
            return hint
    return EXCLUDE_INVALID


def _config_hash_of(row: dict[str, Any]) -> str:
    return str(row.get("config_hash") or "").strip()


def build_series_statistics(
    series_id: str,
    *,
    report: dict[str, Any] | None = None,
    runs: list[dict[str, Any]] | None = None,
    planned_variants: list[str] | tuple[str, ...] | None = None,
    formal_min_repeat_count: int | None = None,
    expected_config_hashes: dict[str, str] | None = None,
    generated_at: str | None = None,
) -> StatisticsSnapshot:
    """从原始运行记录全量重算一个实验组的统计快照(方案 13.10)。

    ``runs`` 未提供时从 ``report`` 提取;两者皆空则产出"无数据"快照。
    ``planned_variants`` 为实验组计划变体列表:零样本变体也进入
    by_variant 并标记"无数据"等级,计划外变体被排除(UNKNOWN_VARIANT)。
    ``formal_min_repeat_count`` 为实验组冻结的正式最小样本门槛,决定
    样本分级;缺省 3(批次口径的兼容缺省)。
    ``expected_config_hashes`` 为实验组冻结的每变体预期配置哈希;提供时
    配置一致性按正式口径直接比较,未提供时按观察主导值(历史兼容)。
    同一批运行记录重算任意次,除 ``generated_at`` 外逐字节一致。
    """
    rows = runs if runs is not None else runs_from_report(report)
    meta = report_meta(report)

    formal_min = max(int(formal_min_repeat_count) if formal_min_repeat_count else 3, 1)
    expected = {
        str(label): str(value) for label, value in (expected_config_hashes or {}).items() if str(value or "").strip()
    }
    config_hash_mode = CONFIG_HASH_MODE_EXPECTED if expected else CONFIG_HASH_MODE_DOMINANT
    planned_set = {str(label) for label in (planned_variants or []) if str(label)}

    excluded: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()
    duplicate_excluded_by_variant: Counter[str] = Counter()
    #: 完成登记的运行数(按唯一运行身份去重后计数,按 run_outcome 分计;
    #: 与后续排除无关,重复上报的同一 run_id 不重复计入物理运行)
    completed_by_variant: Counter[str] = Counter()
    failed_by_variant: Counter[str] = Counter()

    # 第 1 步:字段完整性(缺运行身份或变体字段,无法归位)
    normalized: list[tuple[str, dict[str, Any]]] = []
    for index, row in enumerate(rows):
        run_id = str(row.get("run_id") or "").strip()
        variant_id = str(row.get("variant_label") or "").strip()
        if not run_id or not variant_id:
            excluded.append(
                {
                    "run_id": run_id or f"row-{index}",
                    "variant_id": variant_id,
                    "reason": EXCLUDE_MISSING_FIELDS,
                }
            )
            continue
        normalized.append((variant_id, run_id, row))

    # 第 2 步:运行身份去重(同一 run_id 只统计一次;重复进入质量警告)。
    # 完成/失败计数在去重后进行:计数口径是唯一运行身份,不是输入行数
    deduped: list[tuple[str, dict[str, Any]]] = []
    for variant_id, run_id, row in normalized:
        if run_id in seen_run_ids:
            excluded.append({"run_id": run_id, "variant_id": variant_id, "reason": EXCLUDE_DUPLICATE_RUN_ID})
            duplicate_excluded_by_variant[variant_id] += 1
            continue
        seen_run_ids.add(run_id)
        if str(row.get("run_outcome") or "") == "failed":
            failed_by_variant[variant_id] += 1
        else:
            completed_by_variant[variant_id] += 1
        deduped.append((variant_id, row))

    # 第 3~5 步:有效性 → Agent 执行证据 → 变体归属(固定顺序,单一主因)
    survivors: dict[str, list[dict[str, Any]]] = {}
    for variant_id, row in deduped:
        validity = str(row.get("validity") or "VALID")
        if validity != "VALID":
            excluded.append({"run_id": str(row["run_id"]), "variant_id": variant_id, "reason": _failure_reason(row)})
            continue
        steps = _as_number(row, "actual_agent_steps")
        if steps is None or steps <= 0:
            excluded.append({"run_id": str(row["run_id"]), "variant_id": variant_id, "reason": EXCLUDE_NO_AGENT_LOOP})
            continue
        if planned_set and variant_id not in planned_set:
            excluded.append({"run_id": str(row["run_id"]), "variant_id": variant_id, "reason": EXCLUDE_UNKNOWN_VARIANT})
            continue
        survivors.setdefault(variant_id, []).append(row)

    # 第 6 步:配置一致性(空哈希一律排除;有冻结哈希直接比较,否则观察主导值)
    # 历史兼容口径:无预期哈希的变体取观察主导值,且只在非空哈希中选取
    dominants: dict[str, str] = {}
    for variant_id, rows_of_variant in survivors.items():
        if expected.get(variant_id):
            continue
        non_empty = [_config_hash_of(row) for row in rows_of_variant if _config_hash_of(row)]
        if non_empty:
            dominants[variant_id] = _dominant(non_empty)
    included: dict[str, list[dict[str, Any]]] = {}
    for variant_id, rows_of_variant in sorted(survivors.items()):
        expected_hash = expected.get(variant_id)
        kept: list[dict[str, Any]] = []
        for row in rows_of_variant:
            actual = _config_hash_of(row)
            if not actual:
                # 空 config_hash 无条件排除(比不匹配更具体的原因),永不主导
                excluded.append(
                    {
                        "run_id": str(row["run_id"]),
                        "variant_id": variant_id,
                        "reason": EXCLUDE_EMPTY_CONFIG_HASH,
                    }
                )
            elif expected_hash:
                # 正式口径:actual == 实验组冻结的预期哈希
                if actual == expected_hash:
                    kept.append(row)
                else:
                    excluded.append(
                        {
                            "run_id": str(row["run_id"]),
                            "variant_id": variant_id,
                            "reason": EXCLUDE_CONFIG_MISMATCH,
                            "detail": f"expected={expected_hash}, actual={actual}",
                        }
                    )
            else:
                # 历史兼容:观察主导值只在非空哈希中选取
                dominant = dominants.get(variant_id)
                if dominant is not None and actual != dominant:
                    excluded.append(
                        {
                            "run_id": str(row["run_id"]),
                            "variant_id": variant_id,
                            "reason": EXCLUDE_CONFIG_MISMATCH,
                            "detail": f"expected={dominant}, actual={actual}",
                        }
                    )
                else:
                    kept.append(row)
        included[variant_id] = kept

    # 计划内零样本变体:保留条目并标记"无数据",不在统计里隐身
    for label in sorted(planned_set):
        if label not in included:
            included[label] = []

    # 第 7~8 步:指标提取 + 分组统计与样本等级
    by_variant: dict[str, dict[str, Any]] = {}
    for variant_id, kept in sorted(included.items()):
        stat = VariantStatistics(variant_id=variant_id)
        stat.included_run_ids = sorted(str(row["run_id"]) for row in kept)
        stat.included_count = len(stat.included_run_ids)
        stat.completed_count = completed_by_variant.get(variant_id, 0)
        stat.failed_count = failed_by_variant.get(variant_id, 0)
        variant_excluded = [row for row in excluded if row["variant_id"] == variant_id]
        stat.excluded_count = len(variant_excluded)
        stat.exclusion_reasons = dict(sorted(Counter(row["reason"] for row in variant_excluded).items()))
        stat.config_hashes = sorted({_config_hash_of(row) for row in kept if _config_hash_of(row)})

        step_values = [v for row in kept if (v := _as_number(row, "actual_agent_steps")) is not None]
        duration_values = [v for row in kept if (v := _as_number(row, "duration_ms")) is not None]
        tool_values = [float(len(row.get("tool_calls") or [])) for row in kept]
        stat.actual_agent_steps = _stats_block(step_values) or {}
        stat.duration_ms = _stats_block(duration_values) or {}
        stat.tool_calls_per_run = _stats_block(tool_values) or {}

        for key, target in (("input_tokens", "input_tokens"), ("output_tokens", "output_tokens")):
            values = [v for row in kept if (v := _as_number(row, key)) is not None]
            setattr(stat, target, _stats_block(values))
        success_flags = [row.get("task_success") for row in kept if isinstance(row.get("task_success"), bool)]
        if success_flags:
            stat.success_rate = round(sum(1 for flag in success_flags if flag) / len(success_flags), 4)

        stat.stop_reasons = dict(sorted(Counter(str(row.get("stop_reason")) or "UNSPECIFIED" for row in kept).items()))
        stat.errors = dict(sorted(Counter(str(row.get("error")) for row in kept if row.get("error")).items()))
        # 样本分级:按样本量分级后,兼容口径(未冻结预期哈希)封顶为
        # "观察结果",不冒充"最小正式样本"(修复方案 P1-2)
        level = sample_level_for(len(kept), formal_min)
        if config_hash_mode != CONFIG_HASH_MODE_EXPECTED and level["level"] in (
            SAMPLE_LEVEL_FORMAL,
            SAMPLE_LEVEL_EXTENDED,
        ):
            level = {"level": SAMPLE_LEVEL_OBSERVATION, "label": SAMPLE_LEVEL_LABELS[SAMPLE_LEVEL_OBSERVATION]}
        stat.sample_level = level
        by_variant[variant_id] = stat.to_payload()

    level_rank = [
        SAMPLE_LEVEL_RANK.get(payload.get("sample_level", {}).get("level", ""), 0) for payload in by_variant.values()
    ] or [0]
    overall = min(level_rank)
    overall_level = next(key for key, rank in SAMPLE_LEVEL_RANK.items() if rank == overall)

    # 数据质量警告(修复方案 P0-1/P1-3):重复 run_id 不再隐藏在排除表中。
    # 统计模块只有 run_id 一个身份键,无法判断重复上报与不同物理样本,
    # 只陈述事实,不推断"不同样本",也不输出"门槛因此无法满足"的因果结论
    data_quality_warnings: list[dict[str, Any]] = []
    for variant_id in sorted(duplicate_excluded_by_variant):
        dup_count = duplicate_excluded_by_variant[variant_id]
        data_quality_warnings.append(
            {
                "code": WARNING_DUPLICATE_RUN_IDS,
                "severity": "error",
                "variant_id": variant_id,
                "excluded_count": dup_count,
                "message": (
                    f"检测到重复 run_id(排除 {dup_count} 条),无法判断是否为同一运行重复上报;请核对运行登记与原始记录"
                ),
            }
        )

    notes: list[str] = []
    if not rows:
        notes.append("运行明细为空:报告缺少 runs 或批次尚未完成,统计为空")
    if planned_variants is not None and not expected:
        notes.append(
            "该实验组未冻结预期配置哈希(旧定义或迁移数据),"
            "配置一致性按观察主导值兼容口径:样本只标为观察结果,"
            "不作为正式口径,正式对比不可用"
        )
    if by_variant and all(payload.get("input_tokens") is None for payload in by_variant.values()):
        notes.append("运行记录未持久化输入/输出 Token(方案 11.1 计量写入尚未接入模板路径),Token 指标缺席")
    if by_variant and all(payload.get("success_rate") is None for payload in by_variant.values()):
        notes.append("运行记录未持久化 task_success,第一版不计算 success_rate")

    included_run_ids = sorted(run_id for payload in by_variant.values() for run_id in payload["included_run_ids"])
    excluded.sort(key=lambda row: (row["variant_id"], row["run_id"], row["reason"]))
    definition_hash = meta.get("fixed_conditions_hash") or canonical_hash(
        {
            "template_id": meta.get("template_id"),
            "template_version": meta.get("template_version"),
            "variants": sorted(by_variant),
        }
    )
    generated = generated_at or datetime.now(UTC).isoformat()

    # 比较可用性(修复方案 §6.3):至少两个计划变体各有一个有效样本;
    # 正式对比要求至少两个变体达到 formal_min,且配置一致性必须是
    # 冻结预期哈希口径(修复方案 P1-2:观察主导值兼容口径不得声明正式)。
    # 计划变体即使零样本也存在于 by_variant,不能用 bool(by_variant) 判断。
    candidates = sorted(planned_set) if planned_variants is not None else sorted(by_variant)
    included_counts = {label: len(included.get(label, [])) for label in candidates}
    with_sample = [label for label in candidates if included_counts[label] >= 1]
    at_formal = [label for label in candidates if included_counts[label] >= formal_min]
    available = len(with_sample) >= 2
    formal_available = len(at_formal) >= 2 and config_hash_mode == CONFIG_HASH_MODE_EXPECTED
    if len(candidates) < 2:
        comparison_reason = "计划变体不足两个,无法对比"
    elif not available:
        comparison_reason = "至少两个变体需要有效样本"
    elif len(at_formal) < 2:
        comparison_reason = "部分变体尚未达到正式最小样本"
    elif config_hash_mode != CONFIG_HASH_MODE_EXPECTED:
        comparison_reason = "未冻结预期配置哈希(观察主导值兼容口径),不作为正式对比"
    else:
        comparison_reason = ""

    comparison = {
        "available": available,
        "formal_available": formal_available,
        "reason": comparison_reason,
        "median_duration_ms": {
            variant_id: payload["duration_ms"].get("median")
            for variant_id, payload in sorted(by_variant.items())
            if payload.get("duration_ms")
        },
        "median_agent_steps": {
            variant_id: payload["actual_agent_steps"].get("median")
            for variant_id, payload in sorted(by_variant.items())
            if payload.get("actual_agent_steps")
        },
    }

    snapshot = StatisticsSnapshot(
        series_id=series_id,
        template_id=meta.get("template_id") or "",
        template_version=meta.get("template_version"),
        definition_hash=definition_hash,
        formal_min_repeat_count=formal_min,
        expected_config_hashes=dict(sorted(expected.items())),
        config_hash_mode=config_hash_mode,
        generated_at=generated,
        input_run_count=len(rows),
        included_run_count=len(included_run_ids),
        excluded_run_count=len(excluded),
        included_run_ids=included_run_ids,
        excluded_runs=excluded,
        data_quality_warnings=data_quality_warnings,
        by_variant=by_variant,
        comparison=comparison,
        sample_sufficiency={
            "by_variant": {variant_id: payload["sample_level"] for variant_id, payload in sorted(by_variant.items())},
            "overall_level": overall_level,
            "overall_label": SAMPLE_LEVEL_LABELS.get(overall_level, SAMPLE_LEVEL_LABELS[SAMPLE_LEVEL_NONE]),
        },
        notes=notes,
    )

    payload = snapshot.to_payload()
    payload.pop("snapshot_hash", None)
    payload.pop("generated_at", None)
    snapshot.snapshot_hash = canonical_hash(payload)
    return snapshot
