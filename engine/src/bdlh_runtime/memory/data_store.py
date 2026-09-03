"""通过 Data Service 持久化上下文构建的 Store 适配器。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from bdlh_runtime.data_client import DataClient, DataServiceError

from .store import (
    BUILD_PHASES,
    ActiveBuildConflict,
    BuildIdempotencyConflict,
    BuildNotFound,
    ForbiddenBuild,
    canonical_hash,
)
from .turns import events_with_turns


class DataServiceContextBuildStore:
    """绑定一个所有者的远程 Store；只有显式配置后才启用。"""

    def __init__(self, owner_id: str, client: DataClient | None = None, *, source_type: str) -> None:
        if not owner_id:
            raise ValueError("owner_id is required for data-service context builds")
        self.owner_id = owner_id
        self.client = client or DataClient()
        self.source_type = source_type

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
        self._check_owner(owner_id)
        request_hash = canonical_hash(
            {
                "session_id": session_id,
                "current_request_event_id": current_request_event_id,
                "algorithm": algorithm,
                "source_type": source_type,
            }
        )
        snapshot = {"source_type": source_type, **(config_snapshot or {})}
        try:
            created = self.client.create_context_workbench_build(
                {
                    "accountId": owner_id,
                    "sessionId": session_id,
                    "currentRequestEventId": current_request_event_id,
                    "algorithmVersion": algorithm,
                    "idempotencyKey": idempotency_key,
                    "requestHash": request_hash,
                    "configSnapshot": snapshot,
                }
            )
        except DataServiceError as exc:
            if exc.status_code != 409:
                raise
            code = str(exc.payload.get("errorCode") or "")
            if code == "IDEMPOTENCY_KEY_REUSED":
                raise BuildIdempotencyConflict(idempotency_key) from exc
            if code == "ACTIVE_BUILD_EXISTS":
                raise ActiveBuildConflict(str(exc.payload.get("activeBuildId") or "")) from exc
            raise
        build_id = str(created["buildId"])
        replay = bool(created.get("replay"))
        if not replay:
            row = self._initial_row(build_id, session_id, current_request_event_id, algorithm, source_type)
            row["config_snapshot"] = snapshot
            self._save(row)
        return self.get(build_id, owner_id), replay

    def start_phase(self, build_id: str, phase: str) -> None:
        if phase not in BUILD_PHASES:
            raise ValueError(f"unknown build phase {phase!r}")
        row = self.get(build_id, self.owner_id)
        row["status"] = "RUNNING"
        row["current_phase"] = phase
        step = self._step(row, phase)
        step.update({"status": "RUNNING", "started_at": _utc_now(), "finished_at": None, "duration_ms": None})
        self._save(row)

    def finish_phase(self, build_id: str, phase: str, status: str, detail_code: str) -> None:
        if status not in {"SUCCEEDED", "SKIPPED", "FALLBACK", "FAILED"}:
            raise ValueError(f"unknown step status {status!r}")
        row = self.get(build_id, self.owner_id)
        step = self._step(row, phase)
        finished = datetime.now(UTC)
        started = datetime.fromisoformat(step["started_at"]) if step.get("started_at") else finished
        step.update(
            {
                "status": status,
                "finished_at": finished.isoformat(),
                "duration_ms": max(0, round((finished - started).total_seconds() * 1000)),
                "detail_code": detail_code,
            }
        )
        self._save(row)

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
        artifact_id = self.client.save_context_artifact(
            build_id,
            {
                "accountId": self.owner_id,
                "messages": artifact.get("messages") or [],
                "contentHash": str(artifact.get("message_hash") or ""),
                "tokenCount": int(artifact.get("working_tokens") or 0),
                "tokenizerVersion": str(artifact.get("tokenizer_version") or "unknown"),
                # 工件 Segment 明细快照(data-service Store 下页面"历史摘要复用"的数据源)
                "memorySegments": artifact.get("memory_segments") or [],
            },
        )
        row = self.get(build_id, self.owner_id)
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
            }
        )
        self._save(row)
        return self.get(build_id, self.owner_id)

    def fail(self, build_id: str, error_code: str, message: str) -> None:
        row = self.get(build_id, self.owner_id)
        row["status"] = "FAILED"
        row["error_code"] = error_code
        row["warnings"] = [*(row.get("warnings") or []), f"{error_code}: {message}"]
        current = str(row.get("current_phase") or "")
        if current in BUILD_PHASES:
            step = self._step(row, current)
            if step.get("status") == "RUNNING":
                step.update(
                    {
                        "status": "FAILED",
                        "finished_at": _utc_now(),
                        "detail_code": error_code,
                    }
                )
        self._save(row)

    def get(self, build_id: str, owner_id: str) -> dict[str, Any]:
        self._check_owner(owner_id)
        try:
            payload = self.client.get_context_workbench_build(owner_id, build_id)
        except DataServiceError as exc:
            if exc.status_code == 404:
                raise BuildNotFound(build_id) from exc
            raise
        return self._normalize_build(payload)

    def list_builds_cross_owner(self, limit: int = 50, cursor: int = 0) -> dict[str, Any]:
        """运维脱敏视图的跨所有者构建行(数据服务原始行 → 统一 ops 行形状)。"""

        payload = self.client.list_context_builds_cross_owner(limit, cursor)
        rows = []
        for row in payload.get("builds") or []:
            rows.append(
                {
                    "build_id": _str(row.get("buildId")),
                    "session_id": _str(row.get("sessionId")),
                    "owner_id": _str(row.get("accountId")),
                    "status": _str(row.get("status")),
                    "current_phase": _str(row.get("currentPhase")),
                    "algorithm_version": _str(row.get("algorithmVersion")),
                    "error_code": row.get("errorCode"),
                    "budget": _json_value(row.get("budget")),
                    "llm_usage": _json_value(row.get("llmUsage")),
                    "item_counts": _json_value(row.get("itemCounts")),
                    "agent_run": _json_value(row.get("agentRun")),
                    "config_snapshot": _json_value(row.get("configSnapshot")),
                    "created_at": row.get("createdAt"),
                    "updated_at": row.get("updatedAt"),
                }
            )
        return {
            "builds": rows,
            "total": int(payload.get("total") or 0),
            "next_cursor": payload.get("nextCursor"),
        }

    def latest_for_session(self, owner_id: str, session_id: str) -> dict[str, Any] | None:
        """该所有者某 Session 最近一次构建的轻量摘要;无构建返回 None。"""

        self._check_owner(owner_id)
        payload = self.client.get_latest_context_build(owner_id, session_id)
        if not payload:
            return None
        row = self._normalize_build(payload)
        return {
            "build_id": row["build_id"],
            "status": row["status"],
            "current_phase": row["current_phase"],
            "current_request_event_id": row["current_request_event_id"],
            "algorithm_version": row["algorithm_version"],
            "error_code": row.get("error_code"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    def artifact(self, build_id: str, owner_id: str) -> dict[str, Any]:
        self._check_owner(owner_id)
        build = self.get(build_id, owner_id)
        try:
            payload = self.client.get_context_artifact(owner_id, build_id)
        except DataServiceError as exc:
            if exc.status_code == 404:
                raise BuildNotFound(build_id) from exc
            raise
        messages = payload.get("messages") or []
        memory_segments = payload.get("memorySegments") or payload.get("memory_segments") or []
        source_event_ids: list[str] = []
        turned_events: list[dict[str, Any]] = []
        try:
            from .sources import DatabaseSessionSource

            session, _variants = DatabaseSessionSource(owner_id, self.client).get_session(str(build["session_id"]))
            current_id = str(build["current_request_event_id"])
            current = next(event for event in session.events if event.event_id == current_id)
            source_event_ids = [event.event_id for event in session.events if event.seq < current.seq]
            turned_events = events_with_turns(session.events)
        except (DataServiceError, StopIteration):
            pass
        return {
            "artifact_version": "context-workbench-v1",
            "artifact_id": str(payload.get("artifactId") or ""),
            "build_id": build_id,
            "session_id": build["session_id"],
            "source_type": self.source_type,
            "current_request_event_id": build["current_request_event_id"],
            "algorithm_version": build["algorithm_version"],
            "messages": messages,
            "message_hash": payload.get("contentHash"),
            "working_tokens": int(payload.get("tokenCount") or 0),
            "tokenizer_version": payload.get("tokenizerVersion"),
            "memory_segments": memory_segments,
            "memory_segment_ids": [
                str(row.get("segment_id")) for row in memory_segments if isinstance(row, dict) and row.get("segment_id")
            ],
            "source_event_ids": source_event_ids,
            "events": turned_events,
        }

    def artifact_any_owner(self, build_id: str) -> dict[str, Any]:
        """跨所有者工件读取(仅限 API 层授权判定放行后调用)。"""

        try:
            payload = self.client.get_context_artifact_cross_owner(build_id)
        except DataServiceError as exc:
            if exc.status_code == 404:
                raise BuildNotFound(build_id) from exc
            raise
        owner_id = _str(payload.get("accountId"))
        messages = _json_value(payload.get("messages")) or []
        memory_segments = _json_value(payload.get("memorySegments")) or []
        source_event_ids: list[str] = []
        turned_events: list[dict[str, Any]] = []
        try:
            from .sources import DatabaseSessionSource

            session, _variants = DatabaseSessionSource(owner_id, self.client).get_session(
                _str(payload.get("sessionId"))
            )
            current = next(
                event for event in session.events if event.event_id == _str(payload.get("currentRequestEventId"))
            )
            source_event_ids = [event.event_id for event in session.events if event.seq < current.seq]
            turned_events = events_with_turns(session.events)
        except (DataServiceError, StopIteration):
            pass
        return {
            "artifact_version": "context-workbench-v1",
            "artifact_id": _str(payload.get("artifactId")),
            "build_id": build_id,
            "session_id": _str(payload.get("sessionId")),
            "source_type": self.source_type,
            "current_request_event_id": _str(payload.get("currentRequestEventId")),
            "algorithm_version": _str(payload.get("algorithmVersion")),
            "messages": messages,
            "message_hash": payload.get("contentHash"),
            "working_tokens": int(payload.get("tokenCount") or 0),
            "tokenizer_version": payload.get("tokenizerVersion"),
            "memory_segments": memory_segments,
            "memory_segment_ids": [
                str(row.get("segment_id")) for row in memory_segments if isinstance(row, dict) and row.get("segment_id")
            ],
            "source_event_ids": source_event_ids,
            "events": turned_events,
        }

    def start_agent_run(self, build_id: str, snapshot: dict[str, Any]) -> None:
        row = self.get(build_id, self.owner_id)
        existing = row.get("agent_run")
        if existing and existing.get("status") in {"COMPLETED", "FAILED"}:
            raise RuntimeError("AGENT_RUN_EXISTS")
        row["agent_run"] = dict(snapshot)
        self._save(row)

    def finish_agent_run(
        self,
        build_id: str,
        snapshot: dict[str, Any],
        *,
        llm_usage_patch: dict[str, int] | None = None,
    ) -> None:
        row = self.get(build_id, self.owner_id)
        row["agent_run"] = dict(snapshot)
        if llm_usage_patch:
            usage = dict(row.get("llm_usage") or {})
            usage.update(llm_usage_patch)
            row["llm_usage"] = usage
        self._save(row)

    def _save(self, row: dict[str, Any]) -> None:
        self.client.update_context_workbench_build(
            str(row["build_id"]),
            {
                "accountId": self.owner_id,
                "status": row["status"],
                "currentPhase": row["current_phase"],
                "steps": row.get("steps") or [],
                "budget": row.get("budget") or {},
                "itemCounts": row.get("item_counts") or {},
                "llmUsage": row.get("llm_usage") or {},
                "warnings": row.get("warnings") or [],
                "decisions": row.get("decisions") or [],
                "errorCode": row.get("error_code"),
                "errorMessage": row.get("error_message"),
                "agentRunSnapshot": row.get("agent_run") or {},
            },
        )

    def _initial_row(
        self,
        build_id: str,
        session_id: str,
        current_request_event_id: str,
        algorithm: str,
        source_type: str,
    ) -> dict[str, Any]:
        return {
            "build_id": build_id,
            "session_id": session_id,
            "current_request_event_id": current_request_event_id,
            "algorithm_version": algorithm,
            "source_type": source_type,
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
            "decisions": [],
            "artifact_id": None,
            "error_code": None,
            "error_message": None,
        }

    def _normalize_build(self, payload: dict[str, Any]) -> dict[str, Any]:
        decisions = []
        for decision in payload.get("decisions") or []:
            decisions.append(
                {
                    "item_id": decision.get("item_id") or decision.get("item_key") or decision.get("itemKey"),
                    "action": decision.get("action"),
                    "reason": decision.get("reason"),
                    "input_tokens": decision.get("input_tokens") or decision.get("inputTokens") or 0,
                    "output_tokens": decision.get("output_tokens") or decision.get("outputTokens") or 0,
                    "output_content": decision.get("output_content") or decision.get("outputContent"),
                    "output_hash": decision.get("output_hash") or decision.get("outputHash"),
                    "source_id": decision.get("reference_id") or decision.get("referenceId"),
                }
            )
        return {
            "build_id": str(payload.get("buildId") or payload.get("build_id") or ""),
            "session_id": str(payload.get("sessionId") or payload.get("session_id") or ""),
            "current_request_event_id": str(
                payload.get("currentRequestEventId") or payload.get("current_request_event_id") or ""
            ),
            "algorithm_version": str(payload.get("algorithmVersion") or payload.get("algorithm_version") or ""),
            "source_type": self.source_type,
            "status": str(payload.get("status") or "PENDING"),
            "current_phase": str(payload.get("currentPhase") or payload.get("current_phase") or "LOAD_HISTORY"),
            "steps": payload.get("steps") or [],
            "budget": payload.get("budget") or {},
            "item_counts": payload.get("itemCounts") or payload.get("item_counts") or {},
            "llm_usage": payload.get("llmUsage") or payload.get("llm_usage") or {},
            "warnings": payload.get("warnings") or [],
            "decisions": decisions,
            "config_snapshot": _json_value(payload.get("configSnapshot") or payload.get("config_snapshot")) or {},
            "artifact_id": payload.get("artifactId") or payload.get("artifact_id"),
            "agent_run": payload.get("agentRunSnapshot") or payload.get("agent_run") or None,
            "error_code": payload.get("errorCode") or payload.get("error_code"),
            "created_at": payload.get("createdAt") or payload.get("created_at"),
            "updated_at": payload.get("updatedAt") or payload.get("updated_at"),
        }

    def _check_owner(self, owner_id: str) -> None:
        if owner_id != self.owner_id:
            raise ForbiddenBuild(owner_id)

    @staticmethod
    def _step(row: dict[str, Any], phase: str) -> dict[str, Any]:
        return next(step for step in row["steps"] if step["phase"] == phase)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _str(value: Any) -> str:
    return str(value) if value is not None else ""


def _json_value(value: Any) -> Any:
    """数据服务 JSONB 列以文本返回;解析失败原样返回,不伪造结构。"""

    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value
