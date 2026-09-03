"""上下文构建的文件持久化状态仓库。

这是工作台 P0 第一阶段的本地持久层：提供幂等、每所有者/Session 单活跃构建、
进程重启中断标记和不可变工件文件。生产 PostgreSQL 表接入后由同一接口替换，
不会改变公开 API 契约。
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

BUILD_PHASES = (
    "LOAD_HISTORY",
    "CLASSIFY_AND_SELECT",
    "SUMMARIZE_HISTORY",
    "VALIDATE_AND_PERSIST",
    "ASSEMBLE_CONTEXT",
    "COMPLETED",
)
ACTIVE_BUILD_STATUSES = frozenset({"PENDING", "RUNNING"})
TERMINAL_BUILD_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})


class BuildIdempotencyConflict(RuntimeError):
    """同一所有者幂等键被不同请求复用。"""


class ActiveBuildConflict(RuntimeError):
    """同一所有者/Session 已有活跃构建。"""

    def __init__(self, build_id: str) -> None:
        self.build_id = build_id
        super().__init__(f"session already has active build {build_id}")


class BuildNotFound(LookupError):
    """构建不存在。"""


class ForbiddenBuild(PermissionError):
    """构建不属于当前所有者。"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


class ContextBuildStore:
    """线程安全的构建状态仓库；一个 JSON 文件对应一个 build。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifact_root = self.root / "artifacts"
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._records: dict[str, dict[str, Any]] = {}
        self._load_records()

    def _load_records(self) -> None:
        for path in self.root.glob("*.json"):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            build_id = str(row.get("build_id") or "")
            if not build_id:
                continue
            if row.get("status") in ACTIVE_BUILD_STATUSES:
                row["status"] = "FAILED"
                row["error_code"] = "PROCESS_RESTART"
                row["error_message"] = "构建进程已重启，未自动重放 LLM 请求"
                row["updated_at"] = utc_now()
                self._write(row)
            self._records[build_id] = row

    def create(
        self,
        *,
        owner_id: str,
        session_id: str,
        current_request_event_id: str,
        algorithm: str,
        idempotency_key: str,
        source_type: str,
        config_snapshot: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        request_payload = {
            "session_id": session_id,
            "current_request_event_id": current_request_event_id,
            "algorithm": algorithm,
            "source_type": source_type,
        }
        request_hash = canonical_hash(request_payload)
        with self._lock:
            for row in self._records.values():
                if row["owner_id"] == owner_id and row["idempotency_key"] == idempotency_key:
                    if row["request_hash"] != request_hash:
                        raise BuildIdempotencyConflict(idempotency_key)
                    return self._public(row), True
            for row in self._records.values():
                if (
                    row["owner_id"] == owner_id
                    and row["session_id"] == session_id
                    and row["status"] in ACTIVE_BUILD_STATUSES
                ):
                    raise ActiveBuildConflict(str(row["build_id"]))
            now = utc_now()
            build_id = str(uuid4())
            row = {
                "build_id": build_id,
                "owner_id": owner_id,
                "session_id": session_id,
                "current_request_event_id": current_request_event_id,
                "algorithm_version": algorithm,
                "source_type": source_type,
                "config_snapshot": dict(config_snapshot or {}),
                "idempotency_key": idempotency_key,
                "request_hash": request_hash,
                "status": "PENDING",
                "current_phase": "LOAD_HISTORY",
                "steps": [
                    {
                        "phase": phase,
                        "status": "PENDING",
                        "started_at": None,
                        "finished_at": None,
                        "duration_ms": None,
                        "detail_code": None,
                    }
                    for phase in BUILD_PHASES
                ],
                "budget": {},
                "item_counts": {},
                "llm_usage": {"classification_calls": 0, "summary_calls": 0, "cache_hits": 0},
                "warnings": [],
                "artifact_id": None,
                "decisions": [],
                "agent_run": None,
                "created_at": now,
                "updated_at": now,
                "error_code": None,
                "error_message": None,
            }
            self._records[build_id] = row
            self._write(row)
            return self._public(row), False

    def start_phase(self, build_id: str, phase: str) -> None:
        if phase not in BUILD_PHASES:
            raise ValueError(f"unknown build phase {phase!r}")
        with self._lock:
            row = self._record(build_id)
            row["status"] = "RUNNING"
            row["current_phase"] = phase
            step = self._step(row, phase)
            step["status"] = "RUNNING"
            step["started_at"] = utc_now()
            step["finished_at"] = None
            step["duration_ms"] = None
            row["updated_at"] = utc_now()
            self._write(row)

    def finish_phase(self, build_id: str, phase: str, status: str, detail_code: str) -> None:
        if status not in {"SUCCEEDED", "SKIPPED", "FALLBACK", "FAILED"}:
            raise ValueError(f"unknown step status {status!r}")
        with self._lock:
            row = self._record(build_id)
            step = self._step(row, phase)
            finished = datetime.now(UTC)
            started = datetime.fromisoformat(step["started_at"]) if step["started_at"] else finished
            step["status"] = status
            step["finished_at"] = finished.isoformat()
            step["duration_ms"] = max(0, round((finished - started).total_seconds() * 1000))
            step["detail_code"] = detail_code
            row["updated_at"] = finished.isoformat()
            self._write(row)

    def complete(
        self,
        build_id: str,
        *,
        budget: dict[str, Any],
        item_counts: dict[str, int],
        llm_usage: dict[str, int],
        warnings: list[str],
        decisions: list[dict[str, Any]],
        artifact: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            row = self._record(build_id)
            artifact_id = f"ctxa-{build_id}"
            artifact_path = self.artifact_root / f"{artifact_id}.json"
            artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
            row.update(
                {
                    "status": "COMPLETED",
                    "current_phase": "COMPLETED",
                    "budget": budget,
                    "item_counts": item_counts,
                    "llm_usage": llm_usage,
                    "warnings": warnings,
                    "decisions": decisions,
                    "artifact_id": artifact_id,
                    "updated_at": utc_now(),
                }
            )
            self._write(row)
            return self._public(row)

    def fail(self, build_id: str, error_code: str, message: str) -> None:
        with self._lock:
            row = self._record(build_id)
            row["status"] = "FAILED"
            row["error_code"] = error_code
            row["error_message"] = message
            row["updated_at"] = utc_now()
            current = str(row.get("current_phase") or "")
            if current in BUILD_PHASES:
                step = self._step(row, current)
                if step["status"] == "RUNNING":
                    self.finish_phase(build_id, current, "FAILED", error_code)
            self._write(row)

    def get(self, build_id: str, owner_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._record(build_id)
            if row["owner_id"] != owner_id:
                raise ForbiddenBuild(build_id)
            return self._public(row)

    def list_builds_cross_owner(self, limit: int = 50, cursor: int = 0) -> dict[str, Any]:
        """运维脱敏视图的跨所有者构建行(含 owner_id;内容裁剪在 API 层完成)。"""

        with self._lock:
            rows = sorted(
                self._records.values(),
                key=lambda row: str(row.get("created_at") or ""),
                reverse=True,
            )
            total = len(rows)
            page = rows[cursor : cursor + limit]
            next_cursor = cursor + len(page) if cursor + len(page) < total else None
            return {
                "builds": [{**self._public(row), "owner_id": row["owner_id"]} for row in page],
                "total": total,
                "next_cursor": next_cursor,
            }

    def latest_for_session(self, owner_id: str, session_id: str) -> dict[str, Any] | None:
        """该所有者某 Session 最近一次构建的轻量摘要;无构建返回 None。"""

        with self._lock:
            candidates = [
                row for row in self._records.values() if row["owner_id"] == owner_id and row["session_id"] == session_id
            ]
            if not candidates:
                return None
            latest = max(candidates, key=lambda row: str(row.get("created_at") or ""))
            return {
                "build_id": latest["build_id"],
                "status": latest["status"],
                "current_phase": latest["current_phase"],
                "current_request_event_id": latest["current_request_event_id"],
                "algorithm_version": latest["algorithm_version"],
                "error_code": latest.get("error_code"),
                "created_at": latest.get("created_at"),
                "updated_at": latest.get("updated_at"),
            }

    def start_agent_run(self, build_id: str, snapshot: dict[str, Any]) -> None:
        """写入 Agent 运行起点(RUNNING 快照);已有终态运行时拒绝。"""

        with self._lock:
            row = self._record(build_id)
            existing = row.get("agent_run")
            if existing and existing.get("status") in {"COMPLETED", "FAILED"}:
                raise RuntimeError("AGENT_RUN_EXISTS")
            row["agent_run"] = dict(snapshot)
            row["updated_at"] = utc_now()
            self._write(row)

    def finish_agent_run(
        self, build_id: str, snapshot: dict[str, Any], *, llm_usage_patch: dict[str, int] | None = None
    ) -> None:
        """写入 Agent 运行终态快照,并把 agent_* 用量合并进 llm_usage(分项计量)。"""

        with self._lock:
            row = self._record(build_id)
            row["agent_run"] = dict(snapshot)
            if llm_usage_patch:
                usage = dict(row.get("llm_usage") or {})
                usage.update(llm_usage_patch)
                row["llm_usage"] = usage
            row["updated_at"] = utc_now()
            self._write(row)

    def artifact_any_owner(self, build_id: str) -> dict[str, Any]:
        """跨所有者工件读取(仅限 API 层授权判定放行后调用;不做所有者校验)。"""

        with self._lock:
            row = self._record(build_id)
        artifact_id = row.get("artifact_id")
        if not artifact_id:
            raise BuildNotFound(f"build {build_id} has no artifact")
        path = self.artifact_root / f"{artifact_id}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BuildNotFound(str(artifact_id)) from exc

    def artifact(self, build_id: str, owner_id: str) -> dict[str, Any]:
        row = self.get(build_id, owner_id)
        artifact_id = row.get("artifact_id")
        if not artifact_id:
            raise BuildNotFound(f"build {build_id} has no artifact")
        path = self.artifact_root / f"{artifact_id}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BuildNotFound(str(artifact_id)) from exc

    def _record(self, build_id: str) -> dict[str, Any]:
        try:
            return self._records[build_id]
        except KeyError as exc:
            raise BuildNotFound(build_id) from exc

    @staticmethod
    def _step(row: dict[str, Any], phase: str) -> dict[str, Any]:
        return next(step for step in row["steps"] if step["phase"] == phase)

    def _write(self, row: dict[str, Any]) -> None:
        path = self.root / f"{row['build_id']}.json"
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        hidden = {"owner_id", "idempotency_key", "request_hash"}
        return {key: value for key, value in row.items() if key not in hidden}
