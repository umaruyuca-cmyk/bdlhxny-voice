"""FastAPI 路由（审查文档 §6.3：api_prefix 由应用工厂统一注册）。

路由不实现业务编排，只负责把 HTTP 请求转换为一次 Root Graph 调用，并在
interrupt() 返回时保留 thread_id 供客户端恢复。

api_prefix 来自 Settings.api_prefix，不再硬编码 /api/v1——配置与实际
行为保持一致。
"""

from __future__ import annotations

import asyncio
import json
import hashlib
import logging
import re
from collections.abc import AsyncIterator
from datetime import timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from bdlh_runtime.runtimes.langgraph.graphs.root_graph import initial_state
from bdlh_runtime.cognitive.contracts import InputEvent, PublicResponse
from bdlh_runtime.runtime.application import AgentRuntimeApplication
from bdlh_runtime.runtime.context import RunContext
from bdlh_runtime.runtime.recovery import graph_config
from bdlh_runtime.runtime.run_registry import RunLocation
from bdlh_runtime.runtime.rollout import (
    CognitiveExecutionProgress,
    RuntimePath,
)

from .auth import AuthenticationError, JwtAuthenticator
from .schemas import (
    ChatRequest,
    CreateFinancialTaskRequest,
    ResumeRequest,
    RunRequest,
    RunResponse,
)
from .sse import encode_event


logger = logging.getLogger("bdlh_runtime.api.routes")


class _RolloutExecutionObserver:
    def __init__(self, progress: CognitiveExecutionProgress) -> None:
        self._progress = progress

    def on_domain_request(self, request: Any) -> None:
        del request
        self._progress.domain_request_started = True


def _cognitive_state(
    run_id: str,
    session_id: str,
    response: PublicResponse,
    user_id: str | None = None,
) -> dict[str, Any]:
    waiting = response.response_kind == "ASK_USER"
    failed = response.response_kind in {"BLOCKED", "CAPABILITY_NOT_ENABLED"}
    return {
        "run_id": run_id,
        "thread_id": session_id,
        "user_id": user_id,
        "runtime_path": RuntimePath.COGNITIVE.value,
        "status": "WAITING_USER" if waiting else ("FAILED" if failed else "SUCCESS"),
        "next_stage": "awaiting_user" if waiting else "completed",
        "final_response": response.model_dump(mode="json"),
        "events": [{
            "schema_version": "1.0",
            "event_type": "response.completed",
            "run_id": run_id,
            "runtime_path": RuntimePath.COGNITIVE.value,
            "status": "WAITING_USER" if waiting else ("FAILED" if failed else "COMPLETED"),
            "audit_codes": response.audit_codes,
        }],
    }


class InMemoryRunStore:
    """本地开发运行快照缓存。

    该对象不承担流程恢复；真正的恢复依赖 LangGraph Checkpointer。生产环境
    应替换为可观测性/运行记录存储，而不是扩展此内存字典。
    """

    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}

    def put(self, run_id: str, state: dict[str, Any]) -> None:
        self._runs[run_id] = state

    def get(self, run_id: str) -> dict[str, Any] | None:
        return self._runs.get(run_id)


def config_for(
    run_id: str,
    user_id: str | None = None,
    thread_id: str | None = None,
    checkpoint_id: str | None = None,
) -> dict[str, Any]:
    """构建统一恢复配置；thread_id 优先用传入值（多轮对话），否则等于 run_id。"""

    tid = thread_id or run_id
    config = graph_config(RunContext(thread_id=tid, run_id=run_id, user_id=user_id))
    if checkpoint_id is not None:
        config["configurable"]["checkpoint_id"] = checkpoint_id
    return config


def public_state(run_id: str, state: dict[str, Any]) -> RunResponse:
    """将内部 State 投影为 API 响应，避免泄露完整输入和工具原始数据。"""

    waiting = bool(state.get("__interrupt__"))
    return RunResponse(
        run_id=run_id,
        thread_id=state.get("thread_id"),
        status="WAITING_USER" if waiting else state.get("status", "RUNNING"),
        next_stage=state.get("next_stage"),
        final_response=state.get("final_response"),
        interrupts=state.get("__interrupt__", []),
        events=state.get("events", []),
    )


def chat_answer_text(final_response: Any) -> str:
    """把 Root Graph 的结构化响应投影成聊天页正文。"""

    if final_response is None:
        return ""
    if isinstance(final_response, str):
        return final_response.strip()
    if isinstance(final_response, dict):
        for key in ("answer", "summary", "message", "text"):
            value = final_response.get(key)
            if isinstance(value, str) and value.strip():
                limitations = final_response.get("limitations")
                if isinstance(limitations, list) and limitations:
                    notes = "\n".join(f"- {item}" for item in limitations if str(item).strip())
                    return f"{value.strip()}\n\n限制说明：\n{notes}" if notes else value.strip()
                return value.strip()
        return json.dumps(final_response, ensure_ascii=False, default=str)
    return str(final_response).strip()


_CHAT_NODE_STEPS = {
    "query_graph": "classifying",
    "direct_response": "direct_chat",
    "dispatch_workflow": "react_planning",
    "resolve_instrument": "stock_validating",
    "market_data_graph": "skill_executing",
    "load_portfolio_context": "skill_executing",
    "assemble_analysis": "reading_sources",
    "run_analysis": "skill_executing",
    "validate_analysis": "reading_sources",
    "compose_response": "direct_chat",
}


def chat_step_from_update(update: Any) -> str | None:
    """把 LangGraph 顶层节点更新映射成前端展示阶段。"""

    if not isinstance(update, dict):
        return None
    for node_name in update:
        normalized = str(node_name).split(":", 1)[0]
        step = _CHAT_NODE_STEPS.get(normalized)
        if step:
            return step
    return None


def create_api_app(application: AgentRuntimeApplication, api_prefix: str = "/api/v1") -> FastAPI:
    """按配置创建 FastAPI 应用，路由统一挂在 api_prefix 下（审查 §6.3）。"""

    app = FastAPI(title="BDLH Agent Runtime Analysis Workflow", version="0.1.0")
    store = InMemoryRunStore()
    router = APIRouter(prefix=api_prefix)
    authenticator = JwtAuthenticator(
        secret=application.settings.jwt_secret,
        required=application.settings.auth_required,
    )
    if application.chat_session_store is None:
        from bdlh_runtime.runtime.chat_sessions import create_chat_session_store

        application.chat_session_store = create_chat_session_store()
    chat_sessions = application.chat_session_store

    worker_stop = asyncio.Event()
    worker_task: asyncio.Task[None] | None = None

    async def start_financial_task_worker() -> None:
        nonlocal worker_task
        if not application.settings.financial_task_worker_enabled:
            return
        from bdlh_runtime.runtime.scheduler import run_worker_loop

        worker_task = asyncio.create_task(
            run_worker_loop(
                scheduler=application.task_scheduler,
                outbox_worker=application.notification_outbox_worker,
                poll_seconds=application.settings.financial_task_poll_seconds,
                stop_event=worker_stop,
            ),
            name="bdlh-financial-task-worker",
        )

    async def stop_financial_task_worker() -> None:
        worker_stop.set()
        if worker_task is not None:
            await worker_task

    app.router.add_event_handler("startup", start_financial_task_worker)
    app.router.add_event_handler("shutdown", stop_financial_task_worker)

    def request_user_id(authorization: str | None, claimed_user_id: str | None = None) -> str | None:
        """返回 JWT 中的可信 user_id；开发模式才允许无 Token 的显式 user_id。"""

        try:
            authenticated_user_id = authenticator.authenticate(authorization)
        except AuthenticationError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        normalized_claim = str(claimed_user_id).strip() if claimed_user_id is not None else None
        if authenticated_user_id is not None and normalized_claim not in {None, authenticated_user_id}:
            raise HTTPException(status_code=403, detail="请求 user_id 与登录用户不一致")
        return authenticated_user_id or normalized_claim

    def authorize_run(run_id: str, requester_user_id: str | None, state: dict[str, Any]) -> None:
        """阻止用户读取或恢复其他用户的运行。"""

        location = application.run_registry.get(run_id) if application.run_registry is not None else None
        owner_user_id = location.user_id if location is not None else state.get("user_id")
        if requester_user_id is not None and owner_user_id is not None:
            if str(requester_user_id) != str(owner_user_id):
                raise HTTPException(status_code=403, detail="无权访问该运行")
        elif application.settings.auth_required and owner_user_id is None:
            raise HTTPException(status_code=403, detail="运行缺少用户归属，禁止访问")

    def checkpoint_thread_id(public_thread_id: str, user_id: str | None) -> str:
        """Checkpointer 内部按用户隔离同名会话，公开 thread_id 保持前端原值。"""

        return f"user:{user_id}:thread:{public_thread_id}" if user_id is not None else public_thread_id

    async def register_run_location(
        run_id: str,
        thread_id: str,
        user_id: str | None,
    ) -> None:
        """登记运行及其最新 checkpoint，使同一 thread 下的各次运行可精确查询。"""

        if application.run_registry is None:
            return
        checkpoint_id: str | None = None
        try:
            snapshot = await application.graph.aget_state(
                config_for(run_id, user_id, thread_id=thread_id)
            )
            snapshot_config = getattr(snapshot, "config", None) or {}
            checkpoint_id = snapshot_config.get("configurable", {}).get("checkpoint_id")
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
            pass
        application.run_registry.register(
            RunLocation(
                run_id=run_id,
                thread_id=thread_id,
                user_id=user_id,
                checkpoint_id=checkpoint_id,
            )
        )

    async def load_run_state(run_id: str) -> dict[str, Any] | None:
        """优先从 LangGraph Checkpointer 读取状态，内存快照只作兼容兜底。

        Checkpointer 的 StateSnapshot 会把 interrupt 保存在 ``tasks`` 中，
        不一定直接放进 ``values['__interrupt__']``，这里统一投影成 API 契约。
        """
        location = application.run_registry.get(run_id) if application.run_registry is not None else None
        if (
            location is not None
            and location.runtime_path == RuntimePath.COGNITIVE.value
        ):
            return store.get(run_id)
        thread_id = location.thread_id if location is not None else run_id
        user_id = location.user_id if location is not None else None
        checkpoint_id = location.checkpoint_id if location is not None else None
        try:
            snapshot = await application.graph.aget_state(
                config_for(
                    run_id,
                    user_id,
                    thread_id=thread_id,
                    checkpoint_id=checkpoint_id,
                )
            )
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
            snapshot = None
        if snapshot is not None and getattr(snapshot, "values", None):
            state = dict(snapshot.values)
            interrupts: list[dict[str, Any]] = []
            for task in getattr(snapshot, "tasks", ()) or ():
                for item in getattr(task, "interrupts", ()) or ():
                    interrupts.append({"id": item.id, "value": item.value})
            if interrupts:
                state["__interrupt__"] = interrupts
            return state
        return store.get(run_id)

    async def graph_snapshot(config: dict[str, Any]) -> tuple[dict[str, Any], list[Any], str | None]:
        """读取最新 Graph 状态、interrupt 和 checkpoint_id。"""

        snapshot = await application.graph.aget_state(config)
        state = dict(getattr(snapshot, "values", None) or {})
        interrupts: list[Any] = []
        for task in getattr(snapshot, "tasks", ()) or ():
            interrupts.extend(getattr(task, "interrupts", ()) or ())
        snapshot_config = getattr(snapshot, "config", None) or {}
        checkpoint_id = snapshot_config.get("configurable", {}).get("checkpoint_id")
        return state, interrupts, checkpoint_id

    @router.get("/health")
    async def health() -> dict[str, str]:
        """本地健康检查。"""
        return {"status": "UP", "service": "bdlh-runtime-orchestrator"}

    def authenticated_task_user(authorization: str | None) -> str:
        user_id = request_user_id(authorization)
        if user_id is None:
            raise HTTPException(status_code=401, detail="持续任务需要已认证用户")
        return user_id

    @router.post("/financial-tasks", status_code=201)
    async def create_financial_task(
        payload: CreateFinancialTaskRequest,
        authorization: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        from bdlh_runtime.runtime.tasks import (
            FinancialTask,
            FinancialTaskStatus,
            PriceThresholdCondition,
            TaskAuditEvent,
            task_id_from_idempotency,
            utc_now,
        )

        user_id = authenticated_task_user(authorization)
        normalized_key = str(idempotency_key or "").strip()
        if not normalized_key or len(normalized_key) > 255:
            raise HTTPException(
                status_code=422,
                detail="创建持续任务必须提供 1..255 字符的 Idempotency-Key",
            )
        now = utc_now()
        first_wakeup_at = payload.first_wakeup_at or now
        if first_wakeup_at.tzinfo is None or payload.expires_at.tzinfo is None:
            raise HTTPException(status_code=422, detail="任务时间必须包含时区")
        first_wakeup_at = first_wakeup_at.astimezone(timezone.utc)
        expires_at = payload.expires_at.astimezone(timezone.utc)
        if expires_at <= now or first_wakeup_at >= expires_at:
            raise HTTPException(
                status_code=422,
                detail="expires_at 必须晚于当前时间和 first_wakeup_at",
            )
        fingerprint_payload = payload.model_dump(mode="json")
        creation_fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        task_id = task_id_from_idempotency(user_id, normalized_key)
        task = FinancialTask(
            task_id=task_id,
            authenticated_user_id=user_id,
            status=FinancialTaskStatus.SCHEDULED,
            condition=PriceThresholdCondition(
                symbol=payload.symbol.strip().upper(),
                market=payload.market.strip().upper(),
                instrument_name=payload.instrument_name,
                direction=payload.direction,
                threshold=payload.threshold,
                currency=payload.currency.strip().upper(),
            ),
            confirmation_ref=f"task-confirmation:{task_id}",
            creation_fingerprint=creation_fingerprint,
            cadence_seconds=payload.cadence_seconds,
            next_wakeup_at=first_wakeup_at,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
            audit_events=[TaskAuditEvent(
                event_type="task.scheduled",
                occurred_at=now,
                reason_code="USER_CONFIRMED_PRICE_OBSERVATION",
                details={"confirmation_ref": f"task-confirmation:{task_id}"},
            )],
        )
        created = application.task_store.create(task)
        if created.creation_fingerprint != creation_fingerprint:
            raise HTTPException(
                status_code=409,
                detail="同一 Idempotency-Key 已用于不同的任务创建请求",
            )
        return created.model_dump(mode="json")

    @router.get("/financial-tasks")
    async def list_financial_tasks(
        authorization: str | None = Header(default=None),
        limit: int = Query(default=50, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        user_id = authenticated_task_user(authorization)
        return [
            task.model_dump(mode="json")
            for task in application.task_store.list_for_user(user_id, limit=limit)
        ]

    @router.get("/financial-tasks/{task_id}")
    async def get_financial_task(
        task_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        user_id = authenticated_task_user(authorization)
        task = application.task_store.get(task_id, user_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return task.model_dump(mode="json")

    @router.post("/financial-tasks/{task_id}/cancel")
    async def cancel_financial_task(
        task_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        from bdlh_runtime.runtime.tasks import FinancialTaskStatus, TERMINAL_TASK_STATUSES, utc_now

        user_id = authenticated_task_user(authorization)
        task = application.task_store.get(task_id, user_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.status in TERMINAL_TASK_STATUSES:
            if task.status == FinancialTaskStatus.CANCELLED:
                return task.model_dump(mode="json")
            raise HTTPException(status_code=409, detail=f"任务已处于终态 {task.status.value}")
        if task.status in {
            FinancialTaskStatus.RUNNING,
            FinancialTaskStatus.TRIGGERED,
        }:
            raise HTTPException(
                status_code=409,
                detail="任务正在执行当前唤醒，请在本轮结束后重试取消",
            )
        expected_version = task.version
        task.transition(
            FinancialTaskStatus.CANCELLED,
            reason_code="USER_CANCELLED_TASK",
            now=utc_now(),
        )
        try:
            cancelled = application.task_store.update(task, expected_version=expected_version)
        except RuntimeError as exc:
            if str(exc) != "TASK_VERSION_CONFLICT":
                raise
            current = application.task_store.get(task_id, user_id)
            if current is None:
                raise HTTPException(status_code=404, detail="任务不存在") from exc
            if current.status == FinancialTaskStatus.CANCELLED:
                return current.model_dump(mode="json")
            if current.status in {
                FinancialTaskStatus.RUNNING,
                FinancialTaskStatus.TRIGGERED,
            }:
                raise HTTPException(
                    status_code=409,
                    detail="任务正在执行当前唤醒，请在本轮结束后重试取消",
                ) from exc
            if current.status in TERMINAL_TASK_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail=f"任务已处于终态 {current.status.value}",
                ) from exc
            retry_version = current.version
            current.transition(
                FinancialTaskStatus.CANCELLED,
                reason_code="USER_CANCELLED_TASK",
                now=utc_now(),
            )
            try:
                cancelled = application.task_store.update(
                    current, expected_version=retry_version
                )
            except RuntimeError as retry_exc:
                if str(retry_exc) != "TASK_VERSION_CONFLICT":
                    raise
                raise HTTPException(
                    status_code=409,
                    detail="任务状态已变更，请重试取消",
                ) from retry_exc
        return cancelled.model_dump(mode="json")

    @router.get("/notifications")
    async def list_notifications(
        authorization: str | None = Header(default=None),
        limit: int = Query(default=50, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        user_id = authenticated_task_user(authorization)
        return [
            message.model_dump(mode="json")
            for message in application.notification_outbox.list_for_user(user_id, limit=limit)
        ]

    @router.post("/chat/stream")
    async def chat_stream(
        payload: ChatRequest,
        authorization: str | None = Header(default=None),
    ) -> StreamingResponse:
        """新版单助手页面入口：鉴权后把一轮消息交给 Root Graph。"""

        user_id = request_user_id(authorization)
        message = payload.message.strip()
        if not message:
            raise HTTPException(status_code=422, detail="message 不能为空")

        session = chat_sessions.ensure(payload.session_id, user_id)
        if payload.regenerate:
            chat_sessions.prepare_regeneration(session.session_id, user_id)
        else:
            chat_sessions.add_message(session.session_id, user_id, "user", message)

        routing = application.traffic_router.decide(
            user_id=user_id,
            session_id=session.session_id,
        )
        effective_path = (
            RuntimePath(session.pending_runtime_path)
            if session.pending_run_id and session.pending_thread_id
            and session.pending_runtime_path in {item.value for item in RuntimePath}
            else RuntimePath.LEGACY
            if session.pending_run_id and session.pending_thread_id
            else routing.path
        )
        application.rollout_metrics.increment("selected", path=effective_path)
        logger.info(
            "runtime_path_selected path=%s reason=%s session_id=%s",
            effective_path.value,
            (
                "PENDING_RUN_PATH_STICKY"
                if effective_path != routing.path
                else routing.reason_code
            ),
            session.session_id,
        )
        use_cognitive = effective_path == RuntimePath.COGNITIVE

        if use_cognitive:
            run_id = session.pending_run_id or str(uuid4())
            progress = CognitiveExecutionProgress()
            if application.run_registry is not None:
                application.run_registry.register(RunLocation(
                    run_id=run_id,
                    thread_id=session.session_id,
                    user_id=user_id,
                    runtime_path=RuntimePath.COGNITIVE.value,
                ))

            async def cognitive_chat_event_stream() -> AsyncIterator[str]:
                yield encode_event("message", {
                    "schema_version": "1.0",
                    "type": "agent_run",
                    "runId": run_id,
                    "sessionId": session.session_id,
                    "runtimePath": RuntimePath.COGNITIVE.value,
                    "routingReason": routing.reason_code,
                })
                yield encode_event("message", {
                    "schema_version": "1.0",
                    "type": "status",
                    "step": "classifying",
                })
                try:
                    execution = await application.cognitive_application.run(
                        InputEvent(
                            event_id=f"chat:{run_id}",
                            run_id=run_id,
                            user_id=str(user_id),
                            session_id=session.session_id,
                            message=message,
                        ),
                        observer=_RolloutExecutionObserver(progress),
                    )
                except Exception:
                    application.rollout_metrics.increment(
                        "cognitive_error", path=RuntimePath.COGNITIVE
                    )
                    if progress.automatic_fallback_allowed:
                        application.rollout_metrics.increment(
                            "automatic_fallback", path=RuntimePath.COGNITIVE
                        )
                        internal_thread_id = checkpoint_thread_id(
                            session.session_id, user_id
                        )
                        graph_input = initial_state(
                            run_id,
                            {"message": message},
                            user_id,
                            thread_id=session.session_id,
                        )
                        config = config_for(
                            run_id, user_id, thread_id=internal_thread_id
                        )
                        if application.run_registry is not None:
                            application.run_registry.register(RunLocation(
                                run_id=run_id,
                                thread_id=internal_thread_id,
                                user_id=user_id,
                            ))
                        yield encode_event("message", {
                            "schema_version": "1.0",
                            "type": "status",
                            "step": "fallback_legacy",
                            "runtimePath": RuntimePath.LEGACY.value,
                            "fallbackFrom": RuntimePath.COGNITIVE.value,
                        })
                        try:
                            await application.graph.ainvoke(
                                graph_input,
                                config=config,
                            )
                            latest_config = config_for(
                                run_id, user_id, thread_id=internal_thread_id
                            )
                            state, interrupts, checkpoint_id = await graph_snapshot(
                                latest_config
                            )
                            store.put(run_id, state)
                            if application.run_registry is not None:
                                application.run_registry.register(RunLocation(
                                    run_id=run_id,
                                    thread_id=internal_thread_id,
                                    user_id=user_id,
                                    checkpoint_id=checkpoint_id,
                                ))
                            if interrupts:
                                value = getattr(interrupts[0], "value", None)
                                value = value if isinstance(value, dict) else {}
                                yield encode_event("message", {
                                    "schema_version": "1.0",
                                    "type": "clarification",
                                    "prompt": str(value.get("message") or "请补充完成分析所需的信息。"),
                                    "options": [],
                                })
                                return
                            answer = chat_answer_text(state.get("final_response"))
                            for start in range(0, len(answer), 24):
                                yield encode_event("message", {
                                    "schema_version": "1.0",
                                    "type": "token",
                                    "content": answer[start:start + 24],
                                })
                            chat_sessions.add_message(
                                session.session_id, user_id, "assistant", answer
                            )
                            yield encode_event("message", {
                                "schema_version": "1.0",
                                "type": "done",
                                "status": "COMPLETED",
                                "resultStatus": state.get("status"),
                                "sessionId": session.session_id,
                                "runId": run_id,
                                "runtimePath": RuntimePath.LEGACY.value,
                                "fallbackFrom": RuntimePath.COGNITIVE.value,
                            })
                        except Exception:
                            logger.exception(
                                "Cognitive 前置失败后旧路径回退也失败 run_id=%s", run_id
                            )
                            yield encode_event("message", {
                                "schema_version": "1.0",
                                "type": "error",
                                "code": "COGNITIVE_AND_LEGACY_EXECUTION_FAILED",
                                "message": "分析流程执行失败，请稍后重试。",
                            })
                        return
                    logger.exception(
                        "Cognitive 聊天在领域执行后失败，禁止旧路径重跑 run_id=%s", run_id
                    )
                    yield encode_event("message", {
                        "schema_version": "1.0",
                        "type": "error",
                        "code": "COGNITIVE_EXECUTION_FAILED_AFTER_SIDE_EFFECT",
                        "message": "新路径执行失败；为避免重复调用，本轮不会自动重跑。",
                    })
                    return

                application.rollout_metrics.increment(
                    "completed", path=RuntimePath.COGNITIVE
                )
                response = execution.response
                if response.response_kind == "ASK_USER":
                    chat_sessions.set_pending(
                        session.session_id,
                        user_id,
                        run_id=run_id,
                        thread_id=session.session_id,
                        checkpoint_id=None,
                        runtime_path=RuntimePath.COGNITIVE.value,
                    )
                    yield encode_event("message", {
                        "schema_version": "1.0",
                        "type": "clarification",
                        "prompt": response.message,
                        "options": response.next_steps,
                    })
                    yield encode_event("message", {
                        "schema_version": "1.0",
                        "type": "done",
                        "status": "NEED_CLARIFICATION",
                        "sessionId": session.session_id,
                        "runId": run_id,
                        "runtimePath": RuntimePath.COGNITIVE.value,
                    })
                    return
                answer = chat_answer_text(response.model_dump(mode="json"))
                for start in range(0, len(answer), 24):
                    yield encode_event("message", {
                        "schema_version": "1.0",
                        "type": "token",
                        "content": answer[start:start + 24],
                    })
                    await asyncio.sleep(0)
                chat_sessions.add_message(
                    session.session_id, user_id, "assistant", answer
                )
                chat_sessions.set_pending(
                    session.session_id,
                    user_id,
                    run_id=None,
                    thread_id=None,
                    checkpoint_id=None,
                    runtime_path=None,
                )
                blocked = response.response_kind in {
                    "BLOCKED",
                    "CAPABILITY_NOT_ENABLED",
                }
                yield encode_event("message", {
                    "schema_version": "1.0",
                    "type": "done",
                    "status": "FAILED" if blocked else "COMPLETED",
                    "resultStatus": response.response_kind,
                    "sessionId": session.session_id,
                    "runId": run_id,
                    "runtimePath": RuntimePath.COGNITIVE.value,
                })

            # 旧式闭包在下方声明，于流被消费时再解析。
            return StreamingResponse(
                cognitive_chat_event_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        if session.pending_run_id and session.pending_thread_id:
            run_id = session.pending_run_id
            internal_thread_id = session.pending_thread_id
            match = re.search(r"(?<!\d)\d{6}(?!\d)", message)
            resume_value: dict[str, Any] = {"message": message}
            if match:
                resume_value["symbol"] = match.group(0)
            graph_input: Any = Command(resume=resume_value)
            config = config_for(
                run_id,
                user_id,
                thread_id=internal_thread_id,
                checkpoint_id=session.pending_checkpoint_id,
            )
        else:
            run_id = str(uuid4())
            internal_thread_id = checkpoint_thread_id(session.session_id, user_id)
            graph_input = initial_state(
                run_id,
                {"message": message},
                user_id,
                thread_id=session.session_id,
            )
            config = config_for(run_id, user_id, thread_id=internal_thread_id)
            if application.run_registry is not None:
                application.run_registry.register(
                    RunLocation(run_id=run_id, thread_id=internal_thread_id, user_id=user_id)
                )

        async def _legacy_chat_event_stream(
            *, fallback_from: str | None = None
        ) -> AsyncIterator[str]:
            yield encode_event("message", {
                "schema_version": "1.0",
                "type": "agent_run",
                "runId": run_id,
                "sessionId": session.session_id,
                "runtimePath": RuntimePath.LEGACY.value,
                "routingReason": routing.reason_code,
                "fallbackFrom": fallback_from,
            })
            yield encode_event("message", {
                "schema_version": "1.0",
                "type": "status",
                "step": "classifying",
            })
            last_step = "classifying"
            try:
                async for update in application.graph.astream(
                    graph_input,
                    config=config,
                    stream_mode="updates",
                ):
                    step = chat_step_from_update(update)
                    if step and step != last_step:
                        last_step = step
                        yield encode_event("message", {"type": "status", "step": step})

                # 恢复请求的执行 config 可能固定在旧 checkpoint；读取结果时必须回到
                # thread 最新快照，否则会把已经处理完的 interrupt 再次返回给前端。
                latest_config = config_for(run_id, user_id, thread_id=internal_thread_id)
                state, interrupts, checkpoint_id = await graph_snapshot(latest_config)
                store.put(run_id, state)
                if application.run_registry is not None:
                    application.run_registry.register(RunLocation(
                        run_id=run_id,
                        thread_id=internal_thread_id,
                        user_id=user_id,
                        checkpoint_id=checkpoint_id,
                        runtime_path=RuntimePath.LEGACY.value,
                    ))

                if interrupts:
                    value = getattr(interrupts[0], "value", None)
                    value = value if isinstance(value, dict) else {}
                    prompt = str(value.get("message") or "请补充完成分析所需的信息。")
                    chat_sessions.set_pending(
                        session.session_id,
                        user_id,
                        run_id=run_id,
                        thread_id=internal_thread_id,
                        checkpoint_id=checkpoint_id,
                        runtime_path=RuntimePath.LEGACY.value,
                    )
                    yield encode_event("message", {
                        "type": "clarification",
                        "prompt": prompt,
                        "options": [],
                    })
                    yield encode_event("message", {
                        "type": "done",
                        "status": "NEED_CLARIFICATION",
                        "sessionId": session.session_id,
                        "runId": run_id,
                    })
                    return

                answer = chat_answer_text(state.get("final_response"))
                if not answer:
                    yield encode_event("message", {
                        "type": "error",
                        "message": "分析流程已结束，但没有生成可展示的回答。",
                    })
                    return
                for start in range(0, len(answer), 24):
                    yield encode_event("message", {
                        "type": "token",
                        "content": answer[start:start + 24],
                    })
                    await asyncio.sleep(0)
                chat_sessions.add_message(session.session_id, user_id, "assistant", answer)
                chat_sessions.set_pending(
                    session.session_id,
                    user_id,
                    run_id=None,
                    thread_id=None,
                    checkpoint_id=None,
                    runtime_path=None,
                )
                yield encode_event("message", {
                    "type": "done",
                    "status": "COMPLETED",
                    "resultStatus": state.get("status"),
                    "sessionId": session.session_id,
                    "runId": run_id,
                })
            except Exception as exc:
                logger.exception("聊天流程执行失败，run_id=%s session_id=%s", run_id, session.session_id)
                yield encode_event("message", {
                    "type": "error",
                    "message": "分析流程执行失败，请稍后重试。",
                })

        return StreamingResponse(
            _legacy_chat_event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/conversations")
    async def list_conversations(
        authorization: str | None = Header(default=None),
        mode: str = Query(default="general", max_length=32),
        limit: int = Query(default=30, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        """返回当前登录用户的会话目录；mode 仅为前端兼容字段。"""

        del mode
        user_id = request_user_id(authorization)
        return [{
            "sessionId": session.session_id,
            "title": session.title,
            "messageCount": len(session.messages),
            "updatedAt": session.updated_at.isoformat(),
        } for session in chat_sessions.list_for_user(user_id, limit)]

    @router.get("/conversations/{session_id}")
    async def get_conversation(
        session_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        user_id = request_user_id(authorization)
        session = chat_sessions.get(session_id, user_id)
        if session is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return {
            "session": {
                "sessionId": session.session_id,
                "title": session.title,
                "messageCount": len(session.messages),
                "updatedAt": session.updated_at.isoformat(),
            },
            "messages": [
                {"role": item.role, "content": item.content}
                for item in session.messages
            ],
        }

    @router.delete("/conversations/{session_id}", status_code=204)
    async def delete_conversation(
        session_id: str,
        authorization: str | None = Header(default=None),
    ) -> Response:
        user_id = request_user_id(authorization)
        if not chat_sessions.delete(session_id, user_id):
            raise HTTPException(status_code=404, detail="conversation not found")
        return Response(status_code=204)

    @router.post("/agent-runs")
    async def create_run(
        payload: RunRequest,
        authorization: str | None = Header(default=None),
    ) -> RunResponse:
        """创建并运行新的分析线程。thread_id 可选，传入则延续已有会话（v2.1 P0-7）。"""
        user_id = request_user_id(authorization, payload.user_id)
        run_id = str(uuid4())
        public_thread_id = payload.thread_id or run_id  # 未传则新建会话
        routing = application.traffic_router.decide(
            user_id=user_id,
            session_id=public_thread_id,
        )
        application.rollout_metrics.increment("selected", path=routing.path)
        logger.info(
            "runtime_path_selected path=%s reason=%s run_id=%s thread_id=%s",
            routing.path.value,
            routing.reason_code,
            run_id,
            public_thread_id,
        )
        if routing.path == RuntimePath.COGNITIVE:
            progress = CognitiveExecutionProgress()
            if application.run_registry is not None:
                application.run_registry.register(RunLocation(
                    run_id=run_id,
                    thread_id=public_thread_id,
                    user_id=user_id,
                    runtime_path=RuntimePath.COGNITIVE.value,
                ))
            try:
                execution = await application.cognitive_application.run(
                    InputEvent(
                        event_id=f"run:{run_id}",
                        run_id=run_id,
                        user_id=str(user_id),
                        session_id=public_thread_id,
                        message=payload.message,
                    ),
                    observer=_RolloutExecutionObserver(progress),
                )
            except Exception as exc:
                application.rollout_metrics.increment(
                    "cognitive_error", path=RuntimePath.COGNITIVE
                )
                if not progress.automatic_fallback_allowed:
                    logger.exception(
                        "Cognitive agent-run 在领域执行后失败，禁止旧路径重跑 run_id=%s",
                        run_id,
                    )
                    failed_state = {
                        "run_id": run_id,
                        "thread_id": public_thread_id,
                        "user_id": user_id,
                        "runtime_path": RuntimePath.COGNITIVE.value,
                        "status": "FAILED",
                        "next_stage": "completed",
                        "final_response": {
                            "response_kind": "BLOCKED",
                            "response_structure": "SAFETY_BLOCK",
                            "message": "新路径执行失败；为避免重复调用，本轮不会自动重跑。",
                            "audit_codes": ["COGNITIVE_EXECUTION_FAILED_AFTER_SIDE_EFFECT"],
                        },
                        "events": [],
                    }
                    store.put(run_id, failed_state)
                    return public_state(run_id, failed_state)
                logger.warning(
                    "Cognitive agent-run 前置失败，安全回退旧路径 run_id=%s error=%s",
                    run_id,
                    type(exc).__name__,
                )
                application.rollout_metrics.increment(
                    "automatic_fallback", path=RuntimePath.COGNITIVE
                )
            else:
                state = _cognitive_state(
                    run_id, public_thread_id, execution.response, user_id
                )
                store.put(run_id, state)
                application.rollout_metrics.increment(
                    "completed", path=RuntimePath.COGNITIVE
                )
                return public_state(run_id, state)

        internal_thread_id = checkpoint_thread_id(public_thread_id, user_id)
        request = payload.model_dump(exclude_none=True)
        request.pop("user_id", None)
        if application.run_registry is not None:
            application.run_registry.register(
                RunLocation(run_id=run_id, thread_id=internal_thread_id, user_id=user_id)
            )
        state = await application.graph.ainvoke(
            initial_state(run_id, request, user_id, thread_id=public_thread_id),
            config=config_for(run_id, user_id, thread_id=internal_thread_id),
        )
        await register_run_location(run_id, internal_thread_id, user_id)
        store.put(run_id, state)
        return public_state(run_id, state)

    @router.get("/agent-runs/{run_id}")
    async def get_run(
        run_id: str,
        authorization: str | None = Header(default=None),
    ) -> RunResponse:
        requester_user_id = request_user_id(authorization)
        state = await load_run_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail="run not found")
        authorize_run(run_id, requester_user_id, state)
        return public_state(run_id, state)

    @router.post("/agent-runs/{run_id}/resume")
    async def resume_run(
        run_id: str,
        payload: ResumeRequest,
        authorization: str | None = Header(default=None),
    ) -> RunResponse:
        """使用同一 LangGraph thread_id 恢复用户补充/确认后的运行。"""
        requester_user_id = request_user_id(authorization)
        state_before_resume = await load_run_state(run_id)
        if state_before_resume is None:
            raise HTTPException(status_code=404, detail="run not found")
        authorize_run(run_id, requester_user_id, state_before_resume)
        location = application.run_registry.get(run_id) if application.run_registry is not None else None
        thread_id = location.thread_id if location is not None else state_before_resume.get("thread_id")
        user_id = location.user_id if location is not None else state_before_resume.get("user_id")
        checkpoint_id = location.checkpoint_id if location is not None else None
        if (
            location is not None
            and location.runtime_path == RuntimePath.COGNITIVE.value
        ):
            message = (
                payload.value
                if isinstance(payload.value, str)
                else str(payload.value.get("message") or payload.value.get("symbol") or "").strip()
            )
            if not message:
                raise HTTPException(status_code=422, detail="resume value 缺少 message 或 symbol")
            progress = CognitiveExecutionProgress()
            try:
                execution = await application.cognitive_application.run(
                    InputEvent(
                        event_id=f"resume:{run_id}:{uuid4()}",
                        run_id=run_id,
                        user_id=str(user_id),
                        session_id=thread_id or run_id,
                        message=message,
                    ),
                    observer=_RolloutExecutionObserver(progress),
                )
            except Exception:
                logger.exception("Cognitive run 恢复失败 run_id=%s", run_id)
                failed_state = {
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "runtime_path": RuntimePath.COGNITIVE.value,
                    "status": "FAILED",
                    "next_stage": "completed",
                    "final_response": {
                        "response_kind": "BLOCKED",
                        "response_structure": "SAFETY_BLOCK",
                        "message": "新路径恢复失败，本轮不会切换路径重跑。",
                        "audit_codes": ["COGNITIVE_RESUME_FAILED"],
                    },
                    "events": [],
                }
                store.put(run_id, failed_state)
                return public_state(run_id, failed_state)
            state = _cognitive_state(
                run_id,
                thread_id or run_id,
                execution.response,
                user_id,
            )
            store.put(run_id, state)
            return public_state(run_id, state)
        state = await application.graph.ainvoke(
            Command(resume=payload.value),
            config=config_for(
                run_id,
                user_id,
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
            ),
        )
        await register_run_location(run_id, thread_id or run_id, user_id)
        store.put(run_id, state)
        return public_state(run_id, state)

    async def event_stream(run_id: str) -> AsyncIterator[str]:
        index = 0
        while True:
            state = await load_run_state(run_id)
            if state is None:
                yield encode_event("error", {"message": "run not found"})
                return
            events = state.get("events", [])
            while index < len(events):
                yield encode_event("workflow", events[index])
                index += 1
            if state.get("final_response") or state.get("__interrupt__"):
                return
            await asyncio.sleep(0.1)

    @router.get("/agent-runs/{run_id}/events")
    async def stream_events(
        run_id: str,
        authorization: str | None = Header(default=None),
    ):
        requester_user_id = request_user_id(authorization)
        state = await load_run_state(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail="run not found")
        authorize_run(run_id, requester_user_id, state)
        return StreamingResponse(event_stream(run_id), media_type="text/event-stream")

    app.include_router(router)
    return app
