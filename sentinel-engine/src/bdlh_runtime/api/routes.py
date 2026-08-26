"""FastAPI 应用工厂（审查文档 §6.3：api_prefix 由应用工厂统一注册）。

路由不实现业务编排，只负责把 HTTP 请求转换为一次 Cognitive 执行，并在
ASK_USER 时保留 session/run 供客户端恢复。各资源的端点实现拆分在
``api/routers/`` 下，共享依赖经 ``ApiContext`` 注入（重构方案 D1/P3）；
本文件只保留应用装配。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, FastAPI, Response

from bdlh_runtime.infra.application import AgentRuntimeApplication
from bdlh_runtime.infra.readiness import evaluate_readiness

from .auth import JwtAuthenticator
from .context import ApiContext
from .routers import agent_runs, chat, conversations, demo_events, financial_tasks, notifications


def create_api_app(application: AgentRuntimeApplication, api_prefix: str = "/api/v1") -> FastAPI:
    """按配置创建 FastAPI 应用，路由统一挂在 api_prefix 下（审查 §6.3）。"""

    app = FastAPI(title="Sentinel Engine", version="0.1.0")
    router = APIRouter(prefix=api_prefix)
    authenticator = JwtAuthenticator(
        secret=application.settings.jwt_secret,
        required=application.settings.auth_required,
    )
    if application.chat_session_store is None:
        raise RuntimeError("AgentRuntimeApplication 必须提供 chat_session_store")

    ctx = ApiContext(
        application=application,
        store=application.run_state_reader,
        chat_sessions=application.chat_session_store,
        authenticator=authenticator,
    )

    worker_stop = asyncio.Event()
    worker_task: asyncio.Task[None] | None = None

    async def start_financial_task_worker() -> None:
        nonlocal worker_task
        if not application.settings.financial_task_worker_enabled:
            return
        from bdlh_runtime.infra.scheduler import run_worker_loop

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

    @router.get("/health", name="health")
    async def health() -> dict[str, str]:
        """进程存活探针（liveness）；不检查下游依赖。"""
        return {"status": "UP", "service": "sentinel-engine"}

    @router.get("/ready", name="ready")
    async def ready(response: Response) -> dict:
        """流量就绪探针（readiness）；Java / Registry / 条件 Memory 不通过则 503。"""
        report = evaluate_readiness(application)
        if not report.ready:
            response.status_code = 503
        return report.as_dict()

    # Compose / 运维常用无前缀路径；与 api_prefix 下同名探针语义一致。
    @app.get("/health", name="health_root")
    async def health_root() -> dict[str, str]:
        return {"status": "UP", "service": "sentinel-engine"}

    @app.get("/ready", name="ready_root")
    async def ready_root(response: Response) -> dict:
        report = evaluate_readiness(application)
        if not report.ready:
            response.status_code = 503
        return report.as_dict()

    chat.register(router, ctx)
    conversations.register(router, ctx)
    agent_runs.register(router, ctx)
    financial_tasks.register(router, ctx)
    notifications.register(router, ctx)

    # 演示注入端点：仅演示部署档注册（BDLH_DEMO_MODE=true，设计文档 §4.8、C-4、WO-T1-7）。
    # 非 demo 档路由不注册（404），不依赖「隐藏」。
    if application.settings.demo_mode:
        demo_events.register(router, ctx)

    app.include_router(router)
    return app
