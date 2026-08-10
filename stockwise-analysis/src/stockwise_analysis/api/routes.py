"""FastAPI 路由。

路由不实现业务编排，只负责把 HTTP 请求转换为一次 Root Graph 调用，并在
interrupt() 返回时保留 thread_id 供客户端恢复。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from stockwise_analysis.runtimes.langgraph.graphs.root_graph import initial_state
from stockwise_analysis.runtime.application import StockWiseApplication, create_application
from stockwise_analysis.runtime.context import RunContext
from stockwise_analysis.runtime.recovery import graph_config

from .schemas import ResumeRequest, RunRequest, RunResponse
from .sse import encode_event


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


store = InMemoryRunStore()
application: StockWiseApplication = create_application()
app = FastAPI(title="StockWise Analysis Workflow", version="0.1.0")


def config_for(run_id: str, user_id: str | None = None) -> dict[str, Any]:
    """构建统一恢复配置；所有 API 路径都复用同一 thread_id。"""

    return graph_config(RunContext(thread_id=run_id, run_id=run_id, user_id=user_id))


def public_state(run_id: str, state: dict[str, Any]) -> RunResponse:
    """将内部 State 投影为 API 响应，避免泄露完整输入和工具原始数据。"""

    waiting = bool(state.get("__interrupt__"))
    return RunResponse(
        run_id=run_id,
        status="WAITING_USER" if waiting else state.get("status", "RUNNING"),
        next_stage=state.get("next_stage"),
        final_response=state.get("final_response"),
        interrupts=state.get("__interrupt__", []),
        events=state.get("events", []),
    )


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    """本地健康检查；就绪检查将在外部依赖接入后单独提供。"""

    return {"status": "UP", "service": "stockwise-analysis"}


@app.post("/api/v1/agent-runs")
async def create_run(payload: RunRequest) -> RunResponse:
    """创建并运行新的分析线程。"""

    run_id = str(uuid4())
    request = payload.model_dump(exclude_none=True)
    state = await application.graph.ainvoke(
        initial_state(run_id, request, payload.user_id),
        config=config_for(run_id, payload.user_id),
    )
    store.put(run_id, state)
    return public_state(run_id, state)


@app.get("/api/v1/agent-runs/{run_id}")
async def get_run(run_id: str) -> RunResponse:
    state = store.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="run not found")
    return public_state(run_id, state)


@app.post("/api/v1/agent-runs/{run_id}/resume")
async def resume_run(run_id: str, payload: ResumeRequest) -> RunResponse:
    """使用同一 LangGraph thread_id 恢复用户补充/确认后的运行。"""

    if store.get(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    state = await application.graph.ainvoke(
        Command(resume=payload.value),
        config=config_for(run_id),
    )
    store.put(run_id, state)
    return public_state(run_id, state)


async def event_stream(run_id: str) -> AsyncIterator[str]:
    index = 0
    while True:
        state = store.get(run_id)
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


@app.get("/api/v1/agent-runs/{run_id}/events")
async def stream_events(run_id: str):
    if store.get(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    return StreamingResponse(event_stream(run_id), media_type="text/event-stream")
