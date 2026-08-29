"""旧批次 → 实验组迁移(方案 13.13 第 1–4 条)。

- batch_id 保留为 series_id;
- 报告中的每条运行视为独立 Run(status=done,payload 原样保留,不改写历史);
- ``(variant_id, repeat_index)`` 唯一键:重复运行跳过并计数,不重复统计;
- 从迁移的运行重建第一份统计快照并落盘(纯代码重算);
- 幂等:同 ID 实验组已存在时跳过(``--force`` 才覆盖重建);
- 全程不调用 LLM,不重新执行任何 Agent 运行。

用法::

  python -m bdlh_runtime.experiments.series_migrate --list
  python -m bdlh_runtime.experiments.series_migrate              # 扫描工件目录
  python -m bdlh_runtime.experiments.series_migrate --batch <id> [<id> ...]

报告来源:注入的 data_loader(数据服务 report 列)优先,本地工件目录兜底。
更早期的 eval 工件(无 template_id/runs)按"非模板报告"如实跳过。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable

from bdlh_runtime.experiments.series_store import SeriesRecord, SeriesStore
from bdlh_runtime.statistics.aggregators import build_series_statistics
from bdlh_runtime.statistics.service import persist_snapshot


def artifacts_dir(root: str | Path | None = None) -> Path:
    """批次工件目录(env ``ARTIFACTS_DIR``;与 run_api 同一约定)。"""
    if root is not None:
        return Path(root)
    env = os.getenv("ARTIFACTS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "var" / "artifacts"


def load_report(
    batch_id: str,
    *,
    artifacts_root: str | Path | None = None,
    data_loader: Callable[[str], dict[str, Any] | None] | None = None,
) -> dict[str, Any] | None:
    """批次报告读取:数据服务优先,本地工件兜底;都不存在返回 None。"""
    if data_loader is not None:
        try:
            from_db = data_loader(batch_id)
        except Exception:  # noqa: BLE001 —— data 不可达时走本地工件
            from_db = None
        if isinstance(from_db, dict) and from_db:
            return from_db
    path = artifacts_dir(artifacts_root) / f"{batch_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _template_id_of(report: dict[str, Any]) -> str:
    template_id = str(report.get("template_id") or "")
    if template_id:
        return template_id
    # 压缩对照旧报告无 template_id,定义哈希里有 experiment_definition
    return str((report.get("fixed_conditions") or {}).get("experiment_definition") or "")


def runs_from_legacy_report(report: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """提取可迁移运行;压缩对照旧格式(cells)映射为运行形状。"""
    notes: list[str] = []
    runs = report.get("runs")
    if isinstance(runs, list) and runs:
        return [row for row in runs if isinstance(row, dict)], notes
    cells = report.get("cells")
    if isinstance(cells, list) and cells:
        notes.append("报告缺少 runs:按压缩对照 cells 映射(unit_id→run_id, context_variant→variant_label)")
        mapped: list[dict[str, Any]] = []
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            mapped.append(
                {
                    "run_id": str(cell.get("unit_id") or cell.get("run_id") or ""),
                    "variant_label": str(cell.get("context_variant") or ""),
                    "repeat_index": int(cell.get("repeat_index") or 0),
                    "config_hash": str(cell.get("config_hash") or ""),
                    "governance_profile": "standard",
                    "answer": str(cell.get("answer") or ""),
                    "tool_calls": cell.get("tool_calls") or [],
                    "stop_reason": str(cell.get("stop_reason") or ""),
                    "actual_agent_steps": int(cell.get("actual_agent_steps") or 0),
                    "duration_ms": int(cell.get("duration_ms") or 0),
                    "validity": str(cell.get("validity") or "VALID"),
                    "error": cell.get("error"),
                }
            )
        return mapped, notes
    return [], notes


def _formal_min_of(template_id: str) -> int:
    from bdlh_runtime.experiments.templates import TemplatePlanError, get_template

    try:
        return get_template(template_id).formal_min_repeat_count
    except TemplatePlanError:
        return 3


def migrate_batch(
    batch_id: str,
    report: dict[str, Any],
    *,
    store: SeriesStore,
    statistics_root: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """迁移单个批次;返回结果摘要。幂等:已存在且未 ``force`` 时跳过。"""
    result: dict[str, Any] = {"batch_id": batch_id, "status": "skipped", "notes": [], "migrated_runs": 0}
    if store.get(batch_id) is not None and not force:
        result["reason"] = "实验组已存在(幂等跳过;--force 覆盖重建)"
        return result
    template_id = _template_id_of(report)
    runs, notes = runs_from_legacy_report(report)
    result["notes"].extend(notes)
    if not template_id or not runs:
        result["reason"] = "报告缺少 template_id 或运行明细(非模板/压缩报告),不迁移"
        return result

    # 唯一键去重(13.13 第 3 条):同 (variant_id, repeat_index) 只保留首条
    seen: set[tuple[str, int]] = set()
    entries: list[dict[str, Any]] = []
    duplicates = 0
    malformed = 0
    for row in runs:
        variant = str(row.get("variant_label") or "")
        run_id = str(row.get("run_id") or "")
        if not variant or not run_id:
            malformed += 1
            continue
        repeat = int(row.get("repeat_index") or 0) + 1  # 存储口径:第 1 次起
        key = (variant, repeat)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        entries.append(
            {
                "run_key": f"run-{len(entries) + 1:03d}",
                "variant_id": variant,
                "repeat_index": repeat,
                "idempotency_key": None,
                "request_hash": "",
                "status": "done",
                "created_at": None,
                "error": row.get("error"),
                "payload": row,
            }
        )
    if not entries:
        result["reason"] = "运行明细全部无法归位(缺 run_id/variant_label),不迁移"
        return result

    planned = sorted({entry["variant_id"] for entry in entries})
    record = SeriesRecord(
        series_id=batch_id,
        template_id=template_id,
        template_version=int(report.get("template_version") or 1),
        case_id=str((report.get("fixed_conditions") or {}).get("case_id") or report.get("session_id") or ""),
        title=f"迁移:{template_id} · {batch_id}",
        variant_labels=planned,
        fixed_conditions=report.get("fixed_conditions") or {},
        fixed_conditions_hash=str(report.get("fixed_conditions_hash") or ""),
        formal_min_repeat_count=_formal_min_of(template_id),
        runs=entries,
    )
    if store.get(batch_id) is not None:  # force 覆盖重建
        store.save(record)
    else:
        store.create(record)

    snapshot = build_series_statistics(
        batch_id,
        report={
            "template_id": template_id,
            "template_version": record.template_version,
            "fixed_conditions_hash": record.fixed_conditions_hash,
            "runs": [entry["payload"] for entry in entries],
        },
        planned_variants=planned,
    )
    snapshot_path = persist_snapshot(snapshot.to_payload(), root=statistics_root)
    if duplicates:
        result["notes"].append(f"唯一键去重:跳过重复运行 {duplicates} 条")
    if malformed:
        result["notes"].append(f"无法归位(缺 run_id/variant_label):{malformed} 条")
    result.update(
        status="migrated",
        migrated_runs=len(entries),
        duplicates=duplicates,
        snapshot_path=str(snapshot_path),
        snapshot_hash=snapshot.snapshot_hash,
        by_variant=record.counts_by_variant(),
    )
    return result


def iter_artifact_batch_ids(root: str | Path | None = None) -> list[str]:
    return sorted(path.stem for path in artifacts_dir(root).glob("*.json"))


def migrate_all(
    *,
    store: SeriesStore,
    artifacts_root: str | Path | None = None,
    data_loader: Callable[[str], dict[str, Any] | None] | None = None,
    statistics_root: str | Path | None = None,
    force: bool = False,
    batch_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """按批次 ID 列表(缺省扫描工件目录)逐个迁移,返回逐批结果。"""
    ids = batch_ids if batch_ids is not None else iter_artifact_batch_ids(artifacts_root)
    results: list[dict[str, Any]] = []
    for batch_id in ids:
        report = load_report(batch_id, artifacts_root=artifacts_root, data_loader=data_loader)
        if report is None:
            results.append({"batch_id": batch_id, "status": "skipped", "reason": "报告不存在", "notes": []})
            continue
        results.append(
            migrate_batch(
                batch_id,
                report,
                store=store,
                statistics_root=statistics_root,
                force=force,
            )
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="旧批次 → 实验组迁移(方案 13.13;纯代码,不调用 LLM)")
    parser.add_argument("--batch", nargs="*", help="指定批次 ID;缺省扫描工件目录全部批次")
    parser.add_argument("--list", action="store_true", help="仅列出工件目录中可扫描的批次")
    parser.add_argument("--artifacts-dir", default=None, help="工件目录(env ARTIFACTS_DIR)")
    parser.add_argument("--force", action="store_true", help="已迁移的批次也覆盖重建")
    args = parser.parse_args(argv)

    root = args.artifacts_dir
    if args.list:
        for batch_id in iter_artifact_batch_ids(root):
            report = load_report(batch_id, artifacts_root=root)
            summary = ""
            if isinstance(report, dict):
                summary = (
                    f"template={_template_id_of(report) or '?'}"
                    f" runs={len(report.get('runs') or [])}"
                    f" cells={len(report.get('cells') or [])}"
                )
            print(f"{batch_id}  {summary}")
        return 0

    store = SeriesStore()
    results = migrate_all(
        store=store,
        artifacts_root=root,
        force=args.force,
        batch_ids=args.batch,
    )
    for row in results:
        line = f"[{row['status']}] {row['batch_id']}"
        if row["status"] == "migrated":
            line += f" 运行 {row['migrated_runs']} 条 · 快照 {row['snapshot_hash'][:19]}…"
        elif row.get("reason"):
            line += f" — {row['reason']}"
        print(line)
        for note in row.get("notes") or []:
            print(f"    · {note}")
    migrated = sum(1 for row in results if row["status"] == "migrated")
    print(f"完成:{migrated}/{len(results)} 个批次迁移为实验组")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
