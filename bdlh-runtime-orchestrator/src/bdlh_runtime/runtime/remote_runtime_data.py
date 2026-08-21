"""Java Data Plane 的 Chat、Run Registry 与 History Remote Store。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from bdlh_runtime.contracts.history import AnalysisHistoryRecord

from .chat_sessions import ChatMessage, ChatSession
from .errors import ConfigurationError
from .run_registry import RunLocation


class RuntimeDataClient:
    """同步 HTTP 客户端；所有请求都携带可信 user_id 和内部服务凭证。"""

    def __init__(
        self,
        *,
        base_url: str,
        internal_token: str | None,
        request: Callable[..., Any] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._internal_token = internal_token
        self._request = request

    def call(
        self,
        method: str,
        path: str,
        user_id: str | None,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> dict[str, Any] | None:
        numeric_user_id = _numeric_user_id(user_id)
        params = {"user_id": numeric_user_id, **(query or {})}
        headers = {"X-Internal-Token": self._internal_token} if self._internal_token else {}
        try:
            if self._request is not None:
                response = self._request(
                    method=method,
                    path=path,
                    params=params,
                    json=payload,
                    headers=headers,
                )
                status_code = response.status_code
                if status_code == 404 and allow_not_found:
                    return None
                response.raise_for_status()
                return response.json() if status_code != 204 else {}

            import httpx

            with httpx.Client(timeout=10.0) as client:
                response = client.request(
                    method,
                    f"{self._base_url}{path}",
                    params=params,
                    json=payload,
                    headers=headers,
                )
            if response.status_code == 404 and allow_not_found:
                return None
            response.raise_for_status()
            return response.json() if response.status_code != 204 else {}
        except Exception as exc:
            raise RuntimeError(f"Java Runtime Data API 调用失败: {method} {path}") from exc

    def call_internal(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        if not self._internal_token:
            raise RuntimeError("Java internal API requires JAVA_DATA_INTERNAL_TOKEN")
        headers = {"X-Internal-Token": self._internal_token}
        try:
            if self._request is not None:
                response = self._request(method=method, path=path, params=query or {}, json=payload, headers=headers)
                response.raise_for_status()
                return response.json()
            import httpx

            with httpx.Client(timeout=10.0) as client:
                response = client.request(
                    method, f"{self._base_url}{path}", params=query or {}, json=payload, headers=headers
                )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise RuntimeError(f"Java internal API call failed: {method} {path}") from exc


class RemoteChatSessionStore:
    def __init__(self, client: RuntimeDataClient) -> None:
        self._client = client

    def ensure(self, requested_id: str | None, user_id: str | None) -> ChatSession:
        data = self._client.call(
            "POST",
            "/internal/v1/runtime/sessions",
            user_id,
            payload={"requestedSessionId": requested_id},
        )
        return _chat_session(data, user_id)

    def list_for_user(self, user_id: str | None, limit: int) -> list[ChatSession]:
        data = self._client.call(
            "GET",
            "/internal/v1/runtime/sessions",
            user_id,
            query={"limit": max(1, limit)},
        )
        if not isinstance(data, list):
            raise RuntimeError("Java Runtime Data API 返回的会话列表非法")
        return [_chat_session(item, user_id) for item in data]

    def get(self, session_id: str, user_id: str | None) -> ChatSession | None:
        data = self._client.call(
            "GET",
            f"/internal/v1/runtime/sessions/{session_id}",
            user_id,
            allow_not_found=True,
        )
        return _chat_session(data, user_id) if data is not None else None

    def add_message(self, session_id: str, user_id: str | None, role: str, content: str) -> None:
        if not str(content or "").strip():
            return
        self._client.call(
            "POST",
            f"/internal/v1/runtime/sessions/{session_id}/messages",
            user_id,
            payload={"role": role, "content": content},
        )

    def prepare_regeneration(self, session_id: str, user_id: str | None) -> None:
        self._client.call(
            "POST",
            f"/internal/v1/runtime/sessions/{session_id}/prepare-regeneration",
            user_id,
        )

    def set_pending(
        self,
        session_id: str,
        user_id: str | None,
        *,
        run_id: str | None,
        thread_id: str | None,
        checkpoint_id: str | None,
        runtime_path: str | None = None,
        pause_reason: str | None = None,
        awaiting_route_confirm: bool = False,
    ) -> None:
        self._client.call(
            "PUT",
            f"/internal/v1/runtime/sessions/{session_id}/pending",
            user_id,
            payload={
                "runId": run_id,
                "threadId": thread_id,
                "checkpointId": checkpoint_id,
                "runtimePath": runtime_path,
                "pauseReason": pause_reason,
                "awaitingRouteConfirm": bool(awaiting_route_confirm) if run_id else False,
            },
        )

    def get_verified_entity_state(self, session_id: str, user_id: str | None) -> dict[str, Any] | None:
        session = self.get(session_id, user_id)
        if session is None:
            return None
        state = session.verified_entity_state
        return dict(state) if isinstance(state, dict) else None

    def set_verified_entity_state(
        self, session_id: str, user_id: str | None, state: dict[str, Any] | None
    ) -> None:
        self._client.call(
            "PUT",
            f"/internal/v1/runtime/sessions/{session_id}/verified-entity",
            user_id,
            payload={"verifiedEntityState": state},
        )

    def delete(self, session_id: str, user_id: str | None) -> bool:
        return (
            self._client.call(
                "DELETE",
                f"/internal/v1/runtime/sessions/{session_id}",
                user_id,
                allow_not_found=True,
            )
            is not None
        )


class RemoteRunRegistry:
    def __init__(self, client: RuntimeDataClient) -> None:
        self._client = client

    def register(self, location: RunLocation) -> None:
        self._client.call(
            "PUT",
            f"/internal/v1/runtime/runs/{location.run_id}",
            location.user_id,
            payload={
                "threadId": location.thread_id,
                "checkpointId": location.checkpoint_id,
                "runtimePath": location.runtime_path,
            },
        )

    def get(self, run_id: str, user_id: str | None = None) -> RunLocation | None:
        data = self._client.call(
            "GET",
            f"/internal/v1/runtime/runs/{run_id}",
            user_id,
            allow_not_found=True,
        )
        if data is None:
            return None
        return RunLocation(
            run_id=str(data["runId"]),
            thread_id=str(data["threadId"]),
            user_id=str(user_id),
            checkpoint_id=data.get("checkpointId"),
            runtime_path=str(data.get("runtimePath") or "cognitive_finance"),
        )


class RemoteAnalysisHistoryStore:
    def __init__(self, client: RuntimeDataClient) -> None:
        self._client = client

    def save(self, record: AnalysisHistoryRecord) -> None:
        self._client.call(
            "PUT",
            f"/internal/v1/runtime/history/{record.history_id}",
            record.authenticated_user_id,
            payload={
                "threadId": record.thread_id,
                "runId": record.run_id,
                "status": record.status,
                "payload": record.model_dump(mode="json"),
                "createdAt": record.created_at,
            },
        )

    def get(self, history_id: str, user_id: str | None = None) -> AnalysisHistoryRecord | None:
        data = self._client.call(
            "GET",
            f"/internal/v1/runtime/history/{history_id}",
            user_id,
            allow_not_found=True,
        )
        return _history_record(data) if data is not None else None

    def list_by_thread(self, thread_id: str, user_id: str | None) -> list[AnalysisHistoryRecord]:
        data = self._client.call(
            "GET",
            "/internal/v1/runtime/history",
            user_id,
            query={"thread_id": thread_id},
        )
        if not isinstance(data, list):
            raise RuntimeError("Java Runtime Data API 返回的 History 列表非法")
        return [_history_record(item) for item in data]


def create_remote_runtime_stores(
    *,
    base_url: str | None,
    internal_token: str | None,
    production: bool | None = None,
) -> tuple[RemoteAnalysisHistoryStore, RemoteRunRegistry, RemoteChatSessionStore]:
    del production  # G3：远程 Store 一律要求凭证，不再按环境放宽
    if not base_url:
        raise ConfigurationError("远程 Runtime Store 需要 JAVA_API_BASE_URL")
    if not internal_token:
        raise ConfigurationError("Java Runtime Data API 需要 JAVA_DATA_INTERNAL_TOKEN")
    client = RuntimeDataClient(base_url=base_url, internal_token=internal_token)
    return RemoteAnalysisHistoryStore(client), RemoteRunRegistry(client), RemoteChatSessionStore(client)


def _numeric_user_id(user_id: str | None) -> int:
    value = str(user_id or "").strip()
    if not value.isdigit() or int(value) <= 0:
        raise ConfigurationError("Java Runtime Data API 需要可信的数字 user_id")
    return int(value)


def _chat_session(data: dict[str, Any], user_id: str | None) -> ChatSession:
    verified = data.get("verifiedEntityState")
    return ChatSession(
        session_id=str(data["sessionId"]),
        user_id=user_id,
        title=str(data["title"]),
        messages=[
            ChatMessage(role=str(item["role"]), content=str(item["content"])) for item in data.get("messages", [])
        ],
        pending_run_id=data.get("pendingRunId"),
        pending_thread_id=data.get("pendingThreadId"),
        pending_checkpoint_id=data.get("pendingCheckpointId"),
        pending_runtime_path=data.get("pendingRuntimePath"),
        pause_reason=data.get("pauseReason"),
        awaiting_route_confirm=bool(data.get("awaitingRouteConfirm") or False),
        verified_entity_state=dict(verified) if isinstance(verified, dict) else None,
        updated_at=_timestamp(data["updatedAt"]),
    )


def _history_record(data: dict[str, Any]) -> AnalysisHistoryRecord:
    payload = dict(data.get("payload") or {})
    payload.update(
        {
            "history_id": data["historyId"],
            "thread_id": data["threadId"],
            "run_id": data["runId"],
            "status": data["status"],
            "created_at": data["createdAt"],
        }
    )
    return AnalysisHistoryRecord.model_validate(payload)


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
