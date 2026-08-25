"""实验任务持久化存储:文件落盘,服务重启后可恢复。

- 任务、单元进度和已完成结果写入 ``engine/var/jobs/``(env ``JOBS_DIR`` 可覆盖),
  不只保存在进程内字典或 daemon thread;
- 原子写入(临时文件 + rename),并发保存不产生半写文件;
- 服务重启后 ``recover_interrupted`` 把 QUEUED/RUNNING 任务标记为 INTERRUPTED,
  未完成单元不再永久显示运行中;已完成的单元与结果保持不变;
- 匿名任务保存匿名身份哈希(不保存原始 Cookie 值),只能被同一匿名身份读取或取消;
- 匿名任务固定 ``publishable=false``,不自动进入正式指标和公告。

数据库层对应结构见 db/postgresql/changes/(test_jobs / test_job_units);
本存储是引擎侧可独立运行的持久化实现,SQL 由维护者手动执行后由 data 服务承载。
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# 任务状态机:QUEUED → PREPARING → RUNNING → COMPLETE;任意阶段可进入
# FAILED / CANCELLED / INTERRUPTED;部分单元完成即取消时为 PARTIAL。
JOB_STATUS_QUEUED = "QUEUED"
JOB_STATUS_RUNNING = "RUNNING"
JOB_STATUS_COMPLETE = "COMPLETE"
JOB_STATUS_FAILED = "FAILED"
JOB_STATUS_CANCELLED = "CANCELLED"
JOB_STATUS_INTERRUPTED = "INTERRUPTED"
JOB_STATUS_PARTIAL = "PARTIAL"

#: 单元状态:QUEUED 未开始 / RUNNING 执行中 / COMPLETE 完成 /
#: CANCELLED 取消(仅未开始单元)/ INTERRUPTED 服务中断 / FAILED 失败 / INVALID 无效
UNIT_STATUS_QUEUED = "QUEUED"
UNIT_STATUS_RUNNING = "RUNNING"
UNIT_STATUS_COMPLETE = "COMPLETE"
UNIT_STATUS_CANCELLED = "CANCELLED"
UNIT_STATUS_INTERRUPTED = "INTERRUPTED"
UNIT_STATUS_FAILED = "FAILED"

REQUESTER_ANONYMOUS = "ANONYMOUS"
REQUESTER_OWNER = "OWNER"
REQUESTER_SYSTEM = "SYSTEM"

RUN_PURPOSE_PUBLIC_TRIAL = "PUBLIC_TRIAL"
RUN_PURPOSE_OWNER_EXPERIMENT = "OWNER_EXPERIMENT"
RUN_PURPOSE_SYSTEM_REGRESSION = "SYSTEM_REGRESSION"

_ACTIVE_JOB_STATUSES = frozenset({JOB_STATUS_QUEUED, JOB_STATUS_RUNNING})
_ACTIVE_UNIT_STATUSES = frozenset({UNIT_STATUS_QUEUED, UNIT_STATUS_RUNNING})


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_job_id() -> str:
    return f"job-{uuid.uuid4().hex[:12]}"


def sha256_hex(value: str) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


@dataclass
class JobUnit:
    """一个实验单元(= 一次独立运行)的持久化状态。"""

    seq: int
    unit_id: str
    agent_mode_id: str
    repeat_index: int
    status: str = UNIT_STATUS_QUEUED
    context_variant: str | None = None
    run_id: str | None = None
    actual_agent_steps: int = 0
    stop_reason: str = ""
    duration_ms: int = 0
    task_success: bool | None = None
    validity: str = ""
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class JobRecord:
    """一个实验任务的持久化记录(匿名或维护者)。"""

    job_id: str
    test_type: str  # COMPRESSION_CASE | COMPARISON_CASE
    execution_scope: str  # comparison-full | context-only | current-combo | full-matrix
    status: str = JOB_STATUS_QUEUED
    #: 发起者:ANONYMOUS / OWNER / SYSTEM
    requester_type: str = REQUESTER_ANONYMOUS
    #: 匿名身份哈希(Cookie 原值不落盘);维护者任务为 None
    anonymous_id_hash: str | None = None
    run_purpose: str = RUN_PURPOSE_PUBLIC_TRIAL
    #: 匿名测试固定 False;不具备进入正式发布流程的资格
    publishable: bool = False
    #: 对比用例引用;压缩用例为 None
    case_id: str | None = None
    case_version: int | None = None
    #: 压缩用例引用;对比用例为 None
    session_id: str | None = None
    session_version: int | None = None
    current_event_id: str | None = None
    current_message_hash: str | None = None
    context_variant: str | None = None
    agent_mode_id: str | None = None
    context_artifact_hash: str | None = None
    repeat_count: int = 1
    max_agent_steps: int = 8
    selected_tool_ids: list[str] = field(default_factory=list)
    custom_conditions: bool = False
    tool_catalog_version: str = ""
    fixture_set_id: str = ""
    quota_snapshot: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    cancel_requested: bool = False
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    units: list[JobUnit] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)

    def unit(self, unit_id: str) -> JobUnit | None:
        return next((item for item in self.units if item.unit_id == unit_id), None)

    def completed_unit_count(self) -> int:
        return sum(1 for item in self.units if item.status == UNIT_STATUS_COMPLETE)

    def public_view(self) -> dict[str, Any]:
        """匿名接口可见字段:不含内部提示、gold、未脱敏工具返回与匿名原文。"""
        payload = asdict(self)
        payload.pop("quota_snapshot", None)
        payload.pop("idempotency_key", None)
        return payload


class JobStore:
    """文件持久化任务存储(jobs/<job_id>.json,原子写入)。"""

    def __init__(self, root: str | Path | None = None):
        self._root = Path(root or os.getenv("JOBS_DIR") or (Path(__file__).resolve().parents[3] / "var" / "jobs"))
        self._lock = threading.Lock()

    @property
    def root(self) -> Path:
        return self._root

    def _path(self, job_id: str) -> Path:
        return self._root / f"{job_id}.json"

    def save(self, job: JobRecord) -> None:
        job.updated_at = _now_iso()
        payload = asdict(job)
        self._root.mkdir(parents=True, exist_ok=True)
        target = self._path(job.job_id)
        tmp = target.with_suffix(".tmp")
        with self._lock:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(target)

    def get(self, job_id: str) -> JobRecord | None:
        path = self._path(job_id)
        if not path.is_file():
            return None
        return self._load(path)

    def _load(self, path: Path) -> JobRecord:
        raw = json.loads(path.read_text(encoding="utf-8"))
        units = [JobUnit(**row) for row in raw.pop("units") or []]
        return JobRecord(**raw, units=units)

    def list_for_anonymous(self, anonymous_id_hash: str, *, limit: int = 20) -> list[JobRecord]:
        """匿名身份只能列出自己发起的近期任务。"""
        jobs: list[JobRecord] = []
        for path in sorted(self._root.glob("job-*.json"), reverse=True)[: max(limit * 4, 50)]:
            job = self._load(path)
            if job.anonymous_id_hash == anonymous_id_hash:
                jobs.append(job)
            if len(jobs) >= limit:
                break
        return jobs

    def find_by_idempotency_key(self, key: str) -> JobRecord | None:
        for path in sorted(self._root.glob("job-*.json"), reverse=True)[:200]:
            job = self._load(path)
            if job.idempotency_key == key:
                return job
        return None

    def recover_interrupted(self) -> list[str]:
        """服务重启恢复:活跃任务 → INTERRUPTED,活跃单元 → INTERRUPTED。

        已完成单元与工件保持不变;不自动重跑(避免重复模型费用)。
        返回被标记中断的 job_id 列表。
        """
        interrupted: list[str] = []
        for path in self._root.glob("job-*.json"):
            job = self._load(path)
            if job.status not in _ACTIVE_JOB_STATUSES:
                continue
            had_running_units = False
            for unit in job.units:
                if unit.status in _ACTIVE_UNIT_STATUSES:
                    unit.status = UNIT_STATUS_INTERRUPTED
                    had_running_units = True
            done = job.completed_unit_count()
            if job.cancel_requested:
                job.status = JOB_STATUS_CANCELLED if done == 0 else JOB_STATUS_PARTIAL
            else:
                job.status = JOB_STATUS_INTERRUPTED if had_running_units else JOB_STATUS_PARTIAL
            job.error = "服务重启:任务中断,已完成单元保留,未完成单元不自动重跑"
            self.save(job)
            interrupted.append(job.job_id)
        return interrupted
