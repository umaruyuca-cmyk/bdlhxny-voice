"""实验组(Series)存储(P0-7 13.3):逻辑分组,不负责循环执行。

一个实验组 = 固定实验定义 + 计划变体 + 多个独立 Run 的登记簿:
- ``POST /runs`` 一次只创建一个 Run 条目(幂等键查重、单活跃运行检查、
  repeat_index 分配都在锁内完成);
- 执行由调用方(run_api)在后台线程完成,完成后把运行 payload 写回条目;
- 文件存储 + 临时文件原子替换,与 JobStore 同一模式。

Run 条目状态机:queued → running → done | failed。
done 条目携带完整运行 payload(统计模块直接消费);
failed 条目保留错误,统计模块将其计为排除运行,已完成结果不受影响。
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ACTIVE_STATUSES = ("queued", "running")


class SeriesConflictError(RuntimeError):
    """实验组状态冲突:已有活跃运行等。"""


class SeriesIdempotencyConflict(SeriesConflictError):
    """同一幂等键对应不同请求体;不得静默复用。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class SeriesRecord:
    """实验组:冻结定义 + 独立 Run 登记簿(原始运行记录的事实真源之一)。"""

    series_id: str
    template_id: str
    template_version: int
    case_id: str
    title: str
    variant_labels: list[str]
    fixed_conditions: dict[str, Any]
    fixed_conditions_hash: str
    advanced: dict[str, Any] = field(default_factory=dict)
    preset_id: str | None = None
    formal_min_repeat_count: int = 3
    status: str = "active"  # active | closed
    created_at: str = field(default_factory=_now)
    runs: list[dict[str, Any]] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return dict(self.__dict__)

    def counts_by_variant(self) -> dict[str, int]:
        """每变体已完成(有效证据)运行数;排队/失败不计入样本。"""
        counts = {label: 0 for label in self.variant_labels}
        for row in self.runs:
            label = str(row.get("variant_id") or "")
            if row.get("status") == "done" and label in counts:
                counts[label] += 1
        return counts

    def active_run(self) -> dict[str, Any] | None:
        for row in self.runs:
            if row.get("status") in ACTIVE_STATUSES:
                return row
        return None


class SeriesStore:
    """文件存储:``engine/var/series/<series_id>.json``(env ``SERIES_DIR`` 覆盖)。"""

    def __init__(self, root: str | Path | None = None) -> None:
        self._lock = threading.RLock()
        env = os.getenv("SERIES_DIR")
        if root is not None:
            self._root = Path(root)
        elif env:
            self._root = Path(env)
        else:
            self._root = Path(__file__).resolve().parents[3] / "var" / "series"

    def _path_for(self, series_id: str) -> Path:
        safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in series_id)
        return self._root / f"{safe}.json"

    def create(self, record: SeriesRecord) -> SeriesRecord:
        with self._lock:
            path = self._path_for(record.series_id)
            if path.exists():
                raise SeriesConflictError(f"实验组已存在:{record.series_id}")
            self._root.mkdir(parents=True, exist_ok=True)
            self._write(record)
            return record

    def get(self, series_id: str) -> SeriesRecord | None:
        with self._lock:
            path = self._path_for(series_id)
            if not path.is_file():
                return None
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
        known = set(SeriesRecord.__dataclass_fields__)
        return SeriesRecord(**{key: value for key, value in data.items() if key in known})

    def save(self, record: SeriesRecord) -> None:
        with self._lock:
            self._write(record)

    def _write(self, record: SeriesRecord) -> None:
        path = self._path_for(record.series_id)
        self._root.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record.to_payload(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    # ── 运行登记(全部在锁内完成:查重 → 约束检查 → 分配 → 落盘) ────────────

    def begin_run(
        self,
        series_id: str,
        *,
        variant_id: str,
        idempotency_key: str | None,
        request_hash: str,
    ) -> tuple[dict[str, Any], bool]:
        """登记一个且仅一个运行条目;返回(条目, 是否幂等重放)。

        - 同一幂等键 + 同一请求体:返回已有条目(replayed=True),不新建;
        - 同一幂等键 + 不同请求体:抛 SeriesIdempotencyConflict(409);
        - 已有活跃运行:抛 SeriesConflictError(单活跃运行约束);
        - repeat_index 按该变体已有条目数自动分配(含失败条目)。
        """
        with self._lock:
            record = self.get(series_id)
            if record is None:
                raise SeriesConflictError(f"实验组不存在:{series_id}")
            if idempotency_key:
                for row in record.runs:
                    if row.get("idempotency_key") == idempotency_key:
                        if str(row.get("request_hash") or "") != request_hash:
                            raise SeriesIdempotencyConflict(
                                f"幂等键 {idempotency_key!r} 已绑定不同的运行请求"
                            )
                        return row, True
            if record.active_run() is not None:
                raise SeriesConflictError(
                    "该实验组已有运行进行中;等待完成后再发起下一个样本"
                )
            repeat_index = 1 + sum(
                1 for row in record.runs if str(row.get("variant_id") or "") == variant_id
            )
            entry = {
                "run_key": f"run-{len(record.runs) + 1:03d}",
                "variant_id": variant_id,
                "repeat_index": repeat_index,
                "idempotency_key": idempotency_key,
                "request_hash": request_hash,
                "status": "queued",
                "created_at": _now(),
                "error": None,
                "payload": None,
            }
            record.runs.append(entry)
            self._write(record)
            return entry, False

    def mark_running(self, series_id: str, run_key: str) -> None:
        self._update_entry(series_id, run_key, status="running")

    def complete_run(self, series_id: str, run_key: str, payload: dict[str, Any]) -> None:
        self._update_entry(series_id, run_key, status="done", payload=payload, error=None)

    def fail_run(self, series_id: str, run_key: str, error: str) -> None:
        self._update_entry(series_id, run_key, status="failed", error=error)

    def cancel_run(self, series_id: str, run_key: str) -> None:
        """撤销尚未开始的排队条目(如并发槽位不可用);已开始的条目不动。"""
        with self._lock:
            record = self.get(series_id)
            if record is None:
                return
            before = len(record.runs)
            record.runs = [
                row
                for row in record.runs
                if not (row.get("run_key") == run_key and row.get("status") == "queued")
            ]
            if len(record.runs) != before:
                self._write(record)

    def _update_entry(self, series_id: str, run_key: str, **fields: Any) -> None:
        with self._lock:
            record = self.get(series_id)
            if record is None:
                return
            for row in record.runs:
                if row.get("run_key") == run_key:
                    row.update(fields)
                    self._write(record)
                    return


def run_entry_view(entry: dict[str, Any], *, series_id: str) -> dict[str, Any]:
    """API 展示形态:登记字段 + done 时的运行结果(含逐步证据 payload)。"""
    view = {
        "series_id": series_id,
        "run_key": entry.get("run_key"),
        "variant_id": entry.get("variant_id"),
        "repeat_index": entry.get("repeat_index"),
        "status": entry.get("status"),
        "created_at": entry.get("created_at"),
        "error": entry.get("error"),
    }
    payload = entry.get("payload")
    if isinstance(payload, dict):
        view["run_id"] = payload.get("run_id")
        view["result"] = payload
    return view


class DbSeriesStore:
    """实验组存储(数据库版):状态文档存于 ``run_batches.report`` JSONB。

    - ``series_id`` = 数据服务 ``create_batch`` 生成的 batch_id,与方案
      13.13"batch_id 保留为 series_id"同构;
    - 定义、运行登记簿与运行 payload 同处一份状态文档,数据库是唯一
      事实真源,本地不再落任何实验数据文件;
    - 与文件版同一套约束(幂等键查重、单活跃运行、repeat_index 分配),
      进程内 RLock 保护读改写(单引擎进程部署)。

    ``SeriesStore``(文件版)保留用于单元测试与离线迁移工具。
    """

    STATE_VERSION = "series-state-v1"

    def __init__(self, data_factory: Any) -> None:
        self._data_factory = data_factory
        self._lock = threading.RLock()

    def _data(self) -> Any:
        return self._data_factory()

    def _load(self, series_id: str) -> SeriesRecord | None:
        try:
            report = self._data().get_batch_report(series_id)
        except Exception:  # noqa: BLE001 —— data 不可达视为不存在,调用方按 404/503 处理
            return None
        if not isinstance(report, dict) or report.get("series_state_version") != self.STATE_VERSION:
            return None
        known = set(SeriesRecord.__dataclass_fields__)
        data = dict(report.get("record") or {})
        try:
            return SeriesRecord(**{key: value for key, value in data.items() if key in known})
        except TypeError:
            return None

    def _save(self, record: SeriesRecord) -> None:
        self._data().save_batch_report(
            record.series_id,
            {"series_state_version": self.STATE_VERSION, "record": record.to_payload()},
        )

    def create(self, record: SeriesRecord) -> SeriesRecord:
        """创建实验组批次;series_id 以数据服务生成的 batch_id 为准。"""
        with self._lock:
            batch_id = self._data().create_batch(
                name=record.title,
                experiment_type=f"series:{record.template_id}",
                fixed_conditions={
                    "template_id": record.template_id,
                    "template_version": record.template_version,
                    "case_id": record.case_id,
                    "variant_labels": record.variant_labels,
                    "fixed_conditions_hash": record.fixed_conditions_hash,
                    "formal_min_repeat_count": record.formal_min_repeat_count,
                    "advanced": record.advanced,
                    "preset_id": record.preset_id,
                },
            )
            record.series_id = str(batch_id)
            self._save(record)
            return record

    def get(self, series_id: str) -> SeriesRecord | None:
        with self._lock:
            return self._load(series_id)

    def save(self, record: SeriesRecord) -> None:
        with self._lock:
            self._save(record)

    def begin_run(
        self,
        series_id: str,
        *,
        variant_id: str,
        idempotency_key: str | None,
        request_hash: str,
    ) -> tuple[dict[str, Any], bool]:
        """登记一个且仅一个运行条目;语义与文件版完全一致。"""
        with self._lock:
            record = self._load(series_id)
            if record is None:
                raise SeriesConflictError(f"实验组不存在:{series_id}")
            if idempotency_key:
                for row in record.runs:
                    if row.get("idempotency_key") == idempotency_key:
                        if str(row.get("request_hash") or "") != request_hash:
                            raise SeriesIdempotencyConflict(
                                f"幂等键 {idempotency_key!r} 已绑定不同的运行请求"
                            )
                        return row, True
            if record.active_run() is not None:
                raise SeriesConflictError("该实验组已有运行进行中;等待完成后再发起下一个样本")
            repeat_index = 1 + sum(
                1 for row in record.runs if str(row.get("variant_id") or "") == variant_id
            )
            entry = {
                "run_key": f"run-{len(record.runs) + 1:03d}",
                "variant_id": variant_id,
                "repeat_index": repeat_index,
                "idempotency_key": idempotency_key,
                "request_hash": request_hash,
                "status": "queued",
                "created_at": _now(),
                "error": None,
                "payload": None,
            }
            record.runs.append(entry)
            self._save(record)
            return entry, False

    def mark_running(self, series_id: str, run_key: str) -> None:
        self._update_entry(series_id, run_key, status="running")

    def complete_run(self, series_id: str, run_key: str, payload: dict[str, Any]) -> None:
        self._update_entry(series_id, run_key, status="done", payload=payload, error=None)

    def fail_run(self, series_id: str, run_key: str, error: str) -> None:
        self._update_entry(series_id, run_key, status="failed", error=error)

    def cancel_run(self, series_id: str, run_key: str) -> None:
        with self._lock:
            record = self._load(series_id)
            if record is None:
                return
            before = len(record.runs)
            record.runs = [
                row
                for row in record.runs
                if not (row.get("run_key") == run_key and row.get("status") == "queued")
            ]
            if len(record.runs) != before:
                self._save(record)

    def _update_entry(self, series_id: str, run_key: str, **fields: Any) -> None:
        with self._lock:
            record = self._load(series_id)
            if record is None:
                return
            for row in record.runs:
                if row.get("run_key") == run_key:
                    row.update(fields)
                    self._save(record)
                    return
