"""统计服务(P0-7 13.10):每次从原始运行记录全量重算,可选落盘留痕。

- 快照是派生数据:重建不产生任何 LLM 请求,删除后可完全重建;
- 快照目录默认 ``engine/var/statistics/``(env ``STATISTICS_DIR`` 覆盖);
- 写入采用临时文件 + 原子替换,与 JobStore 同一模式。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from bdlh_runtime.statistics.aggregators import build_series_statistics
from bdlh_runtime.statistics.repository import runs_from_report

SNAPSHOT_VERSION_IN_FILENAME = False  # 保留扩展位:未来按 series_id+版本归档


def snapshot_dir(*, root: str | Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    env = os.getenv("STATISTICS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "var" / "statistics"


def snapshot_path(series_id: str, *, root: str | Path | None = None) -> Path:
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in series_id)
    return snapshot_dir(root=root) / f"{safe}.json"


def build_snapshot(
    series_id: str,
    *,
    report: dict[str, Any] | None = None,
    planned_variants: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """从批次报告(或注入的运行记录)重算统计快照并返回 payload。"""
    runs = runs_from_report(report)
    snapshot = build_series_statistics(
        series_id,
        report=report,
        runs=runs,
        planned_variants=planned_variants,
    )
    return snapshot.to_payload()


def persist_snapshot(payload: dict[str, Any], *, root: str | Path | None = None) -> Path:
    """原子保存统计快照(临时文件 + replace),用于留痕与审计比对。"""
    directory = snapshot_dir(root=root)
    directory.mkdir(parents=True, exist_ok=True)
    path = snapshot_path(str(payload.get("series_id", "unknown")), root=root)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_snapshot(series_id: str, *, root: str | Path | None = None) -> dict[str, Any] | None:
    """读取已落盘快照;不存在返回 None。快照仅作留痕,展示永远重算。"""
    path = snapshot_path(series_id, root=root)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
