"""data 服务的内部 HTTP 客户端。

运行服务不直接连接 PostgreSQL；固定题库和运行记录统一经过数据服务读写。
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class DataServiceError(RuntimeError):
    """数据服务不可用或拒绝请求。"""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


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
        self._request("POST", f"/batches/{batch_id}/report", json={"report": report})

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
        expect_json: bool = True,
    ) -> Any:
        status, response = self._request_raw(method, path, json=json)
        response.raise_for_status()
        return response.json() if expect_json else None

    def _request_raw(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> tuple[int, httpx.Response]:
        if not self._token.strip():
            raise DataServiceError("DATA_INTERNAL_TOKEN is not configured")
        try:
            response = httpx.request(
                method,
                f"{self._base_url}{path}",
                headers={"X-Internal-Token": self._token},
                json=json,
                timeout=10.0,
            )
            return response.status_code, response
        except httpx.HTTPError as exc:
            raise DataServiceError(f"data service request failed: {method} {path}: {exc}") from exc


def _error_message(response: httpx.Response, default: str) -> str:
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("error"):
            return str(body["error"])
    except (ValueError, AttributeError):
        pass
    return default
