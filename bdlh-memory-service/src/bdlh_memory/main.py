from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query

from .config import Settings
from .domain import MemoryCandidate, SearchRequest
from .mem0_gateway import UnavailableMem0Gateway, create_gateway
from .persistence import InMemoryInboxRepository, PostgresInboxRepository
from .pool import build_pool
from .rocketmq_consumer import RocketMqMemoryConsumer
from .service import MemoryApplication


def create_app(settings: Settings | None = None, application: MemoryApplication | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    pool = None
    if application is None:
        try:
            gateway = create_gateway(settings)
        except Exception:
            gateway = UnavailableMem0Gateway()
        if settings.postgres_dsn:
            pool = build_pool(settings.postgres_dsn)
            inbox = PostgresInboxRepository(pool)
        else:
            inbox = InMemoryInboxRepository()
        application = MemoryApplication(gateway, inbox)

    def require_internal_token(token: Annotated[str | None, Header(alias="X-Internal-Token")] = None) -> None:
        if settings.internal_token and token == settings.internal_token:
            return
        if settings.environment == "production" or settings.internal_token:
            raise HTTPException(status_code=401, detail="invalid internal service credential")

    def require_user_scope(
        authenticated_user_id: Annotated[str | None, Header(alias="X-Authenticated-User-Id")] = None,
    ) -> str:
        if not authenticated_user_id:
            raise HTTPException(status_code=401, detail="missing authenticated user scope")
        return authenticated_user_id

    consumer = RocketMqMemoryConsumer(application, settings.rocketmq_endpoints) if settings.rocketmq_enabled else None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if consumer is not None:
            consumer.start()
        try:
            yield
        finally:
            if consumer is not None:
                consumer.shutdown()
            if pool is not None:
                pool.close()

    app = FastAPI(title="BDLH Memory Service", version="0.1.0", lifespan=lifespan)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ready"}

    @app.post("/internal/v1/memories/search")
    async def search(
        request: SearchRequest,
        _: None = Depends(require_internal_token),
        authenticated_user_id: str = Depends(require_user_scope),
    ) -> list[dict]:
        if request.user_id != authenticated_user_id:
            raise HTTPException(status_code=403, detail="user scope mismatch")
        return [record.model_dump() for record in await application.search(request)]

    @app.get("/internal/v1/memories/{memory_id}")
    async def get(
        memory_id: str,
        user_id: str = Query(min_length=1),
        _: None = Depends(require_internal_token),
        authenticated_user_id: str = Depends(require_user_scope),
    ) -> dict:
        if user_id != authenticated_user_id:
            raise HTTPException(status_code=403, detail="user scope mismatch")
        result = await application.get(memory_id)
        if result is None or str(result.get("user_id", "")) != user_id:
            raise HTTPException(status_code=404, detail="memory not found")
        return result

    @app.delete("/internal/v1/memories/{memory_id}", status_code=204)
    async def delete(
        memory_id: str,
        user_id: str = Query(min_length=1),
        _: None = Depends(require_internal_token),
        authenticated_user_id: str = Depends(require_user_scope),
    ) -> None:
        if user_id != authenticated_user_id:
            raise HTTPException(status_code=403, detail="user scope mismatch")
        result = await application.get(memory_id)
        if result is None or str(result.get("user_id", "")) != user_id:
            raise HTTPException(status_code=404, detail="memory not found")
        await application.delete(memory_id)

    @app.delete("/internal/v1/users/{user_id}/memories", status_code=204)
    async def delete_user(
        user_id: str,
        _: None = Depends(require_internal_token),
        authenticated_user_id: str = Depends(require_user_scope),
    ) -> None:
        if user_id != authenticated_user_id:
            raise HTTPException(status_code=403, detail="user scope mismatch")
        await application.delete_user(user_id)

    @app.post("/internal/v1/events/memory-candidate", status_code=202)
    async def consume_for_test_or_bridge(
        candidate: MemoryCandidate,
        _: None = Depends(require_internal_token),
        authenticated_user_id: str = Depends(require_user_scope),
    ) -> dict[str, bool]:
        if candidate.authenticated_user_id != authenticated_user_id:
            raise HTTPException(status_code=403, detail="user scope mismatch")
        return {"accepted": await application.consume(candidate)}

    return app


app = create_app()
