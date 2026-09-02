"""data 服务的内部 HTTP 客户端。

运行服务不直接连接 PostgreSQL；固定题库和运行记录统一经过数据服务读写。
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class DataServiceError(RuntimeError):
    """数据服务不可用或拒绝请求。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class DataClient:
    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self._base_url = (base_url or os.getenv("DATA_API_BASE_URL", "http://data:8080/internal/v1")).rstrip("/")
        self._token = token if token is not None else os.getenv("DATA_INTERNAL_TOKEN", "")

    def list_cases(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/cases")
        if not isinstance(payload, list):
            raise DataServiceError("data service returned an invalid case catalog")
        return payload

    def get_tool_catalog(self) -> dict[str, Any]:
        payload = self._request("GET", "/tool-catalog")
        if not isinstance(payload, dict):
            raise DataServiceError("data service returned an invalid tool catalog")
        return payload

    def get_tool_fixtures(self, fixture_set_id: str, *, version: int = 1) -> dict[str, Any]:
        payload = self._request("GET", f"/tool-fixtures/{fixture_set_id}?version={version}")
        if not isinstance(payload, dict):
            raise DataServiceError("data service returned an invalid tool fixture set")
        return payload

    def list_context_sessions(self, owner_id: str) -> list[dict[str, Any]]:
        """读取当前所有者的生产上下文 Session 摘要。"""

        payload = self._request("GET", "/context/sessions", params={"accountId": owner_id})
        sessions = payload.get("sessions") if isinstance(payload, dict) else None
        if not isinstance(sessions, list):
            raise DataServiceError("data service returned an invalid context session catalog")
        return sessions

    def get_context_session(self, owner_id: str, session_id: str) -> dict[str, Any]:
        """读取一份生产 Session 及其只追加事件。"""

        payload = self._request("GET", f"/context/sessions/{session_id}", params={"accountId": owner_id})
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            raise DataServiceError("data service returned an invalid context session")
        return payload

    def save_context_session(self, payload: dict[str, Any]) -> None:
        """写入或追加生产 Session；事件幂等由 session_id/event_id 保证。"""

        self._request("POST", "/context/sessions", json=payload, expect_json=False)

    def create_context_workbench_build(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._request("POST", "/context/builds", json=payload)
        if not isinstance(result, dict):
            raise DataServiceError("data service returned an invalid context build")
        return result

    def update_context_workbench_build(self, build_id: str, payload: dict[str, Any]) -> None:
        self._request("PUT", f"/context/builds/{build_id}", json=payload, expect_json=False)

    def get_context_workbench_build(self, owner_id: str, build_id: str) -> dict[str, Any]:
        payload = self._request("GET", f"/context/builds/{build_id}", params={"accountId": owner_id})
        if not isinstance(payload, dict):
            raise DataServiceError("data service returned an invalid context build")
        return payload

    def get_latest_context_build(self, owner_id: str, session_id: str) -> dict[str, Any] | None:
        """某 Session 最近一次构建;无构建(404)返回 None,不抛错。"""

        try:
            payload = self._request(
                "GET",
                f"/context/sessions/{session_id}/latest-build",
                params={"accountId": owner_id},
            )
        except DataServiceError as exc:
            if exc.status_code == 404:
                return None
            raise
        if not isinstance(payload, dict):
            raise DataServiceError("data service returned an invalid context build")
        return payload

    def save_context_artifact(self, build_id: str, payload: dict[str, Any]) -> str:
        result = self._request("POST", f"/context/builds/{build_id}/artifact", json=payload)
        if not isinstance(result, dict) or not result.get("artifactId"):
            raise DataServiceError("data service returned an invalid context artifact id")
        return str(result["artifactId"])

    def get_context_artifact(self, owner_id: str, build_id: str) -> dict[str, Any]:
        payload = self._request(
            "GET",
            f"/context/builds/{build_id}/artifact",
            params={"accountId": owner_id},
        )
        if not isinstance(payload, dict):
            raise DataServiceError("data service returned an invalid context artifact")
        return payload

    def list_memory_segments(self, owner_id: str, session_id: str) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            f"/context/sessions/{session_id}/memory-segments",
            params={"accountId": owner_id},
        )
        segments = payload.get("segments") if isinstance(payload, dict) else None
        if not isinstance(segments, list):
            raise DataServiceError("data service returned an invalid memory segment list")
        return segments

    def save_memory_segment(self, session_id: str, payload: dict[str, Any]) -> str:
        result = self._request("POST", f"/context/sessions/{session_id}/memory-segments", json=payload)
        if not isinstance(result, dict) or not result.get("segmentId"):
            raise DataServiceError("data service returned an invalid memory segment id")
        return str(result["segmentId"])

    # ── 上下文细粒度 RBAC(授权/审计/跨所有者运维视图,内部接口) ──

    def create_context_access_grant(
        self,
        owner_id: str,
        grantee_id: str,
        *,
        scope: str = "ARTIFACT_READ",
        build_id: str | None = None,
    ) -> dict[str, Any]:
        result = self._request(
            "POST",
            "/context/ops/access-grants",
            json={
                "ownerAccountId": owner_id,
                "granteeAccountId": grantee_id,
                "scope": scope,
                "buildId": build_id,
            },
        )
        if not isinstance(result, dict):
            raise DataServiceError("data service returned an invalid access grant")
        return result

    def list_context_access_grants(self, owner_id: str) -> list[dict[str, Any]]:
        payload = self._request("GET", "/context/ops/access-grants", params={"ownerAccountId": owner_id})
        grants = payload.get("grants") if isinstance(payload, dict) else None
        if not isinstance(grants, list):
            raise DataServiceError("data service returned an invalid access grant list")
        return grants

    def revoke_context_access_grant(self, owner_id: str, grant_id: str) -> None:
        self._request(
            "DELETE",
            f"/context/ops/access-grants/{grant_id}",
            params={"ownerAccountId": owner_id},
            expect_json=False,
        )

    def has_context_grant(self, owner_id: str, grantee_id: str, build_id: str) -> bool:
        payload = self._request(
            "GET",
            "/context/ops/access-grants/active",
            params={
                "ownerAccountId": owner_id,
                "granteeAccountId": grantee_id,
                "buildId": build_id,
            },
        )
        return bool(payload.get("granted")) if isinstance(payload, dict) else False

    def has_context_grant_for_grantee(self, grantee_id: str, build_id: str) -> bool:
        """被授权方视角的跨所有者下载权限判定(无需指明 owner)。"""

        payload = self._request(
            "GET",
            "/context/ops/access-grants/active-for-grantee",
            params={"granteeAccountId": grantee_id, "buildId": build_id},
        )
        return bool(payload.get("granted")) if isinstance(payload, dict) else False

    def get_context_artifact_cross_owner(self, build_id: str) -> dict[str, Any]:
        """跨所有者工件读取(调用前必须已通过授权判定)。"""

        payload = self._request("GET", f"/context/ops/builds/{build_id}/artifact")
        if not isinstance(payload, dict):
            raise DataServiceError("data service returned an invalid context artifact")
        return payload

    def write_context_audit(
        self,
        account_id: str | None,
        action: str,
        *,
        succeeded: bool = True,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._request(
            "POST",
            "/context/ops/audit",
            json={
                "accountId": account_id,
                "action": action,
                "succeeded": succeeded,
                "detail": detail or {},
            },
            expect_json=False,
        )

    def list_context_audit(
        self,
        account_id: str | None = None,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if account_id is not None:
            params["accountId"] = account_id
        payload = self._request("GET", "/context/ops/audit", params=params)
        events = payload.get("events") if isinstance(payload, dict) else None
        if not isinstance(events, list):
            raise DataServiceError("data service returned an invalid audit list")
        return events

    def list_context_builds_cross_owner(self, limit: int = 50, cursor: int = 0) -> dict[str, Any]:
        payload = self._request("GET", "/context/ops/builds", params={"limit": limit, "cursor": cursor})
        if not isinstance(payload, dict) or not isinstance(payload.get("builds"), list):
            raise DataServiceError("data service returned an invalid cross-owner build list")
        return payload

    # ── P2 定时分析(采样源、抽检结果、分析运行) ──

    def list_recent_context_segments(self, limit: int = 5) -> list[dict[str, Any]]:
        payload = self._request("GET", "/context/ops/segments/recent", params={"limit": limit})
        segments = payload.get("segments") if isinstance(payload, dict) else None
        if not isinstance(segments, list):
            raise DataServiceError("data service returned an invalid segment sample list")
        return segments

    def save_context_quality_check(self, payload: dict[str, Any]) -> None:
        self._request("POST", "/context/ops/segment-quality-checks", json=payload, expect_json=False)

    def list_context_quality_checks(
        self,
        account_id: str | None = None,
        *,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if account_id is not None:
            params["accountId"] = account_id
        if session_id is not None:
            params["sessionId"] = session_id
        payload = self._request("GET", "/context/ops/segment-quality-checks", params=params)
        checks = payload.get("checks") if isinstance(payload, dict) else None
        if not isinstance(checks, list):
            raise DataServiceError("data service returned an invalid quality check list")
        return checks

    def start_context_analysis_run(self, trigger: str) -> str:
        result = self._request("POST", "/context/ops/analysis-runs", json={"triggerSource": trigger})
        if not isinstance(result, dict) or not result.get("runId"):
            raise DataServiceError("data service returned an invalid analysis run id")
        return str(result["runId"])

    def finish_context_analysis_run(self, run_id: str, payload: dict[str, Any]) -> None:
        self._request("PUT", f"/context/ops/analysis-runs/{run_id}", json=payload, expect_json=False)

    def list_context_analysis_runs(self, limit: int = 5) -> list[dict[str, Any]]:
        payload = self._request("GET", "/context/ops/analysis-runs", params={"limit": limit})
        runs = payload.get("runs") if isinstance(payload, dict) else None
        if not isinstance(runs, list):
            raise DataServiceError("data service returned an invalid analysis run list")
        return runs


    def get_case_variant_context(self, case_id: str, version: int, variant_id: str) -> dict[str, Any]:
        """变体上下文条目(压缩对照输入):优先 fixture_context_items,兼容 data_fixture。"""
        payload = self._request("GET", f"/cases/{case_id}/versions/{version}/variants/{variant_id}/context")
        if not isinstance(payload, dict):
            raise DataServiceError("data service returned an invalid variant context")
        return payload

    def create_batch(self, *, name: str, experiment_type: str, fixed_conditions: dict[str, Any]) -> str:
        payload = self._request(
            "POST",
            "/batches",
            json={"name": name, "experimentType": experiment_type, "fixedConditions": fixed_conditions},
        )
        return str(payload["batchId"])

    def create_run(self, payload: dict[str, Any]) -> str:
        result = self._request("POST", "/runs", json=payload)
        return str(result["runId"])

    def get_batch(self, batch_id: str) -> dict[str, Any]:
        payload = self._request("GET", f"/batches/{batch_id}")
        if not isinstance(payload, dict):
            raise DataServiceError("data service returned an invalid batch")
        return payload

    def list_batches(self, *, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
        """批次列表(所有者视角,新到旧;cursor=上一页最后一条批次 id)。"""
        path = f"/batches?limit={min(max(int(limit), 1), 100)}"
        if cursor:
            path += f"&cursor={cursor}"
        payload = self._request("GET", path)
        if not isinstance(payload, dict):
            raise DataServiceError("data service returned an invalid batch list")
        return payload

    def save_batch_report(self, batch_id: str, report: dict[str, Any]) -> None:
        """批次执行报告落库(报告读取的第一来源;列缺失/未执行迁移时由调用方降级)。"""
        # data 服务端点返回 ResponseEntity<Void>(200 空 body),与 complete_batch 同口径
        self._request("POST", f"/batches/{batch_id}/report", json={"report": report}, expect_json=False)

    def get_batch_report(self, batch_id: str) -> dict[str, Any] | None:
        """读取批次执行报告;无报告(未完成/历史批次/未迁移列)返回 None,不抛错。"""
        try:
            payload = self._request("GET", f"/batches/{batch_id}/report")
        except (DataServiceError, httpx.HTTPError):
            return None
        report = payload.get("report") if isinstance(payload, dict) else None
        return report if isinstance(report, dict) and report else None

    def complete_batch(self, batch_id: str, status: str) -> None:
        self._request(
            "POST",
            f"/batches/{batch_id}/complete",
            json={"status": status},
            expect_json=False,
        )

    def save_evaluation(
        self,
        run_id: str,
        *,
        checks: dict[str, Any],
        metrics: dict[str, Any],
        valid_run: bool,
        status: str = "COMPLETE",
        evaluator_version: str = "fixed-rules-v1",
    ) -> None:
        self._request(
            "POST",
            f"/runs/{run_id}/evaluation",
            json={
                "evaluatorVersion": evaluator_version,
                "validRun": valid_run,
                "status": status,
                "checks": checks,
                "metrics": metrics,
            },
            expect_json=False,
        )

    def save_events(self, run_id: str, events: list[dict[str, Any]]) -> None:
        """运行事件流(run_events):九类事件,sequence 单调递增。"""
        self._request(
            "POST",
            f"/runs/{run_id}/events",
            json={"events": events},
            expect_json=False,
        )

    def save_context_build(self, run_id: str, build: dict[str, Any]) -> None:
        """上下文构建报告(context_builds/context_items/decisions/messages)。"""
        self._request(
            "POST",
            f"/runs/{run_id}/context-builds",
            json=build,
            expect_json=False,
        )

    def save_model_calls(self, run_id: str, calls: list[dict[str, Any]]) -> None:
        """模型调用明细(model_calls + model_call_messages 消息快照)。"""
        self._request(
            "POST",
            f"/runs/{run_id}/model-calls",
            json={"calls": calls},
            expect_json=False,
        )

    def save_tool_calls(self, run_id: str, calls: list[dict[str, Any]]) -> None:
        """工具调用明细(tool_calls):成功/失败/被拦截(DENIED)。"""
        self._request(
            "POST",
            f"/runs/{run_id}/tool-calls",
            json={"calls": calls},
            expect_json=False,
        )

    def save_guardrail_checks(self, run_id: str, checks: list[dict[str, Any]]) -> None:
        """治理检查明细(guardrail_checks):四时点拦截记录。"""
        self._request(
            "POST",
            f"/runs/{run_id}/guardrail-checks",
            json={"checks": checks},
            expect_json=False,
        )

    def save_measurements(self, run_id: str, measurements: dict[str, Any]) -> None:
        """分阶段耗时与 token 汇总(run_measurements)。"""
        self._request(
            "POST",
            f"/runs/{run_id}/measurements",
            json=measurements,
            expect_json=False,
        )

    def save_artifact(
        self,
        run_id: str,
        *,
        artifact_type: str,
        storage_ref: str,
        content_hash: str,
        public: bool = False,
    ) -> None:
        """统一工件登记(run_artifacts):与 ARTIFACTS_DIR 文件双写。"""
        self._request(
            "POST",
            f"/runs/{run_id}/artifacts",
            json={
                "artifactType": artifact_type,
                "storageRef": storage_ref,
                "contentHash": content_hash,
                "publicArtifact": public,
            },
            expect_json=False,
        )

    def get_run_detail(self, run_id: str) -> dict[str, Any]:
        payload = self._request("GET", f"/runs/{run_id}/detail")
        if not isinstance(payload, dict):
            raise DataServiceError("data service returned an invalid run detail")
        return payload

    def get_run_events(self, run_id: str) -> list[dict[str, Any]]:
        """轻量事件历史(SSE 无发布器时的补发真源;payload 已结构化)。"""
        payload = self._request("GET", f"/runs/{run_id}/events")
        if not isinstance(payload, list):
            raise DataServiceError("data service returned an invalid run event list")
        return payload

    def update_model_config(self, run_id: str, model_config: dict[str, Any]) -> None:
        """运行配置补全(提前建行后,运行完成回写完整 modelConfig)。"""
        self._request(
            "POST",
            f"/runs/{run_id}/model-config",
            json={"modelConfig": model_config},
            expect_json=False,
        )

    def fail_stale_runs(self, batch_id: str) -> int:
        """引擎重启后清理本批次的孤儿运行行;返回受影响行数。"""
        payload = self._request("POST", f"/batches/{batch_id}/fail-stale-runs", json={})
        if not isinstance(payload, dict):
            return 0
        return int(payload.get("failedRuns") or 0)

    def search_batch_tool_calls(
        self,
        batch_id: str,
        *,
        tool: str | None = None,
        status: str | None = None,
        audit_code: str | None = None,
        argument_key: str | None = None,
        argument_value: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        """批次级工具调用检索(阶段三):facets/results/storageBytes。"""
        params: dict[str, Any] = {"limit": limit}
        for key, value in (
            ("tool", tool),
            ("status", status),
            ("auditCode", audit_code),
            ("argumentKey", argument_key),
            ("argumentValue", argument_value),
        ):
            if value:
                params[key] = value
        payload = self._request("GET", f"/batches/{batch_id}/tool-calls/search", params=params)
        if not isinstance(payload, dict):
            raise DataServiceError("data service returned an invalid tool call search payload")
        return payload

    def complete_run(
        self,
        run_id: str,
        output: dict[str, Any],
        *,
        status: str = "COMPLETE",
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """真实状态透传(架构 §7.1):INVALID/FAILED 运行的 agent_runs.status
        不再恒为 COMPLETE;能力统计口径仍以 evaluation_results.status 为准。"""
        payload: dict[str, Any] = {"status": status, "output": output}
        if error_category:
            payload["errorCategory"] = error_category
        if error_message:
            payload["errorMessage"] = error_message
        self._request(
            "POST",
            f"/runs/{run_id}/complete",
            json=payload,
            expect_json=False,
        )

    def login(
        self,
        *,
        username: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        status, response = self._request_raw(
            "POST",
            "/auth/login",
            json={"username": username, "password": password, "ipAddress": ip_address, "userAgent": user_agent},
        )
        if status == 200:
            return response.json()
        raise DataServiceError(_error_message(response, "登录失败"), status_code=status)

    def verify_session(self, token: str) -> dict[str, Any] | None:
        status, response = self._request_raw("POST", "/auth/verify", json={"token": token})
        if status == 200:
            return response.json()
        return None

    def logout(self, token: str) -> None:
        self._request_raw("POST", "/auth/logout", json={"token": token})

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        expect_json: bool = True,
    ) -> Any:
        status, response = self._request_raw(method, path, json=json, params=params)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                error_payload = response.json()
            except ValueError:
                error_payload = None
            raise DataServiceError(
                _error_message(response, f"data service returned HTTP {response.status_code}"),
                status_code=response.status_code,
                payload=error_payload if isinstance(error_payload, dict) else None,
            ) from exc
        return response.json() if expect_json else None

    def _request_raw(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[int, httpx.Response]:
        if not self._token.strip():
            raise DataServiceError("DATA_INTERNAL_TOKEN is not configured")
        try:
            response = httpx.request(
                method,
                f"{self._base_url}{path}",
                headers={"X-Internal-Token": self._token},
                json=json,
                params=params,
                timeout=10.0,
            )
            return response.status_code, response
        except httpx.HTTPError as exc:
            raise DataServiceError(f"data service request failed: {method} {path}: {exc}") from exc


def _error_message(response: httpx.Response, default: str) -> str:
    try:
        body = response.json()
        if isinstance(body, dict):
            if body.get("error"):
                return str(body["error"])
            if body.get("message"):
                return str(body["message"])
            if body.get("errorCode"):
                return str(body["errorCode"])
    except (ValueError, AttributeError):
        pass
    return default
