"""纯代码聚合(P0-7 13.8):过滤 → 归一 → 按变体汇总 → 样本分级。

设计约束(方案 13.6/13.14):
- 只读取入参运行记录,统计重算不产生任何 LLM 请求;
- 无效、失败或证据不完整的运行进入 ``excluded_runs`` 并给出原因;
- 同一 run_id 只统计一次;
- 同一变体内 config_hash 与主导值不一致的运行不混入对照
  (变体之间 config 不同是实验本身,不在此排除);
- 未持久化的指标(如 Token、task_success)如实缺席,不以 0 冒充。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from statistics import median
from typing import Any

from bdlh_runtime.statistics.models import (
    EXCLUDE_CONFIG_MISMATCH,
    EXCLUDE_DUPLICATE_RUN_ID,
    EXCLUDE_INVALID,
    EXCLUDE_LLM_UNAVAILABLE,
    EXCLUDE_MISSING_FIELDS,
    EXCLUDE_NO_AGENT_LOOP,
    SAMPLE_LEVEL_LABELS,
    SAMPLE_LEVEL_NONE,
    SAMPLE_LEVEL_RANK,
    StatisticsSnapshot,
    VariantStatistics,
    canonical_hash,
    sample_level_for,
)
from bdlh_runtime.statistics.repository import report_meta, runs_from_report

#: error 文本中出现的失败指向(与 template_runner 的 LLM_UNAVAILABLE 标记对齐)
_FAILURE_HINT_REASONS = ("LLM_UNAVAILABLE",)


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
    """出现最多的取值;并列时取字典序最小,保证确定性。"""
    counts = Counter(values)
    best = max(counts.values())
    return sorted(value for value, count in counts.items() if count == best)[0]


def _failure_reason(row: dict[str, Any]) -> str:
    error = str(row.get("error") or "")
    for hint in _FAILURE_HINT_REASONS:
        if hint in error:
            return hint
    return EXCLUDE_INVALID


def build_series_statistics(
    series_id: str,
    *,
    report: dict[str, Any] | None = None,
    runs: list[dict[str, Any]] | None = None,
    planned_variants: list[str] | tuple[str, ...] | None = None,
    generated_at: str | None = None,
) -> StatisticsSnapshot:
    """从原始运行记录全量重算一个实验组的统计快照(方案 13.10)。

    ``runs`` 未提供时从 ``report`` 提取;两者皆空则产出"无数据"快照。
    ``planned_variants`` 为实验组计划变体列表:零样本变体也进入
    by_variant 并标记"无数据"等级(方案 13.9/13.12)。
    同一批运行记录重算任意次,除 ``generated_at`` 外逐字节一致。
    """
    rows = runs if runs is not None else runs_from_report(report)
    meta = report_meta(report)

    excluded: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()
    candidates: dict[str, list[dict[str, Any]]] = {}

    # 第一遍:身份归一 + 去重(同一 run_id 只统计一次)
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
        if run_id in seen_run_ids:
            excluded.append(
                {"run_id": run_id, "variant_id": variant_id, "reason": EXCLUDE_DUPLICATE_RUN_ID}
            )
            continue
        seen_run_ids.add(run_id)
        normalized.append((variant_id, row))

    # 第二遍:有效性 + 证据完整性(是否真实进入模型循环)
    for variant_id, row in normalized:
        validity = str(row.get("validity") or "VALID")
        if validity != "VALID":
            excluded.append(
                {"run_id": str(row["run_id"]), "variant_id": variant_id, "reason": _failure_reason(row)}
            )
            continue
        steps = _as_number(row, "actual_agent_steps")
        if steps is None or steps <= 0:
            excluded.append(
                {"run_id": str(row["run_id"]), "variant_id": variant_id, "reason": EXCLUDE_NO_AGENT_LOOP}
            )
            continue
        candidates.setdefault(variant_id, []).append(row)

    # 第三遍:变体内冻结配置一致性(与主导 config_hash 不同的运行不混入)
    included: dict[str, list[dict[str, Any]]] = {}
    for variant_id, rows_of_variant in sorted(candidates.items()):
        hashes = [str(row.get("config_hash") or "") for row in rows_of_variant]
        dominant = _dominant(hashes)
        kept: list[dict[str, Any]] = []
        for row in rows_of_variant:
            if str(row.get("config_hash") or "") != dominant:
                excluded.append(
                    {
                        "run_id": str(row["run_id"]),
                        "variant_id": variant_id,
                        "reason": EXCLUDE_CONFIG_MISMATCH,
                    }
                )
            else:
                kept.append(row)
        included[variant_id] = kept

    # 计划内零样本变体:保留条目并标记"无数据",不在统计里隐身
    for label in sorted(set(planned_variants or [])):
        if label and label not in included:
            included[label] = []

    by_variant: dict[str, dict[str, Any]] = {}
    for variant_id, kept in sorted(included.items()):
        stat = VariantStatistics(variant_id=variant_id)
        stat.included_run_ids = sorted(str(row["run_id"]) for row in kept)
        stat.config_hashes = sorted({str(row.get("config_hash") or "") for row in kept})
        stat.excluded_count = sum(1 for row in excluded if row["variant_id"] == variant_id)

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

        stat.stop_reasons = dict(
            sorted(Counter(str(row.get("stop_reason")) or "UNSPECIFIED" for row in kept).items())
        )
        stat.errors = dict(
            sorted(Counter(str(row.get("error")) for row in kept if row.get("error")).items())
        )
        stat.sample_level = sample_level_for(len(kept))
        by_variant[variant_id] = stat.to_payload()

    level_rank = [
        SAMPLE_LEVEL_RANK.get(payload.get("sample_level", {}).get("level", ""), 0)
        for payload in by_variant.values()
    ] or [0]
    overall = min(level_rank)
    overall_level = next(key for key, rank in SAMPLE_LEVEL_RANK.items() if rank == overall)

    notes: list[str] = []
    if not rows:
        notes.append("运行明细为空:报告缺少 runs 或批次尚未完成,统计为空")
    if by_variant and all(payload.get("input_tokens") is None for payload in by_variant.values()):
        notes.append(
            "运行记录未持久化输入/输出 Token(方案 11.1 计量写入尚未接入模板路径),Token 指标缺席"
        )
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
    generated = generated_at or datetime.now(timezone.utc).isoformat()

    comparison = {
        "available": bool(by_variant),
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
        generated_at=generated,
        included_run_ids=included_run_ids,
        excluded_runs=excluded,
        by_variant=by_variant,
        comparison=comparison,
        sample_sufficiency={
            "by_variant": {
                variant_id: payload["sample_level"] for variant_id, payload in sorted(by_variant.items())
            },
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
