"""项目所有者运行 API + 匿名受限测试接口。

维护者接口不接受问题正文、系统提示词或工具列表;公开展示部署不包含此服务。
匿名接口(/api/v1/public/*)只接受固定编号与允许的配置字段,
不接受任意问题、系统提示、工具定义、Mock 返回、模型地址或密钥。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from bdlh_runtime.data_client import DataClient, DataServiceError
from bdlh_runtime.evaluation.ab_eval import DEFAULT_INTERLEAVE_SEED, _report_payload, load_cases, run_ab_eval
from bdlh_runtime.evaluation.context_eval import COMPARISON_VARIANTS
from bdlh_runtime.evaluation.run_telemetry import (
    ARTIFACT_VERSION,
    RunRecord,
    artifact_hash_of,
    build_run_artifact,
    validity_of,
    verify_artifact_hash,
)
from bdlh_runtime.experiments import AGENT_MODE_IDS as _AGENT_MODE_IDS
from bdlh_runtime.experiments.compression import public_session_overview
from bdlh_runtime.experiments.job_store import JobStore, sha256_hex
from bdlh_runtime.experiments.public_service import AnonymousJobService, PublicTestError
from bdlh_runtime.infra.env import load_deploy_env

ARTIFACTS_DIR = Path(os.getenv("ARTIFACTS_DIR", "/app/artifacts"))

#: 匿名身份 Cookie:不可预测随机值、HttpOnly(JS 不可读)、SameSite=Lax;
#: 数据库/任务只保存其 sha256 哈希。Secure 由部署层 HTTPS 保证(本地 http 不加)。
ANON_COOKIE_NAME = "ts_anon"
ANON_COOKIE_MAX_AGE = 60 * 60 * 24 * 30

_job_store = JobStore()

app = FastAPI(
    title="Private Run API",
    version="1",
    # 生产最小暴露：私有服务不开放交互文档与 OpenAPI schema
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.on_event("startup")
def recover_jobs_on_startup() -> None:
    """服务启动:注入 deploy/.env 并恢复未完成任务。

    env 装载放在 startup(而非 import):测试用 TestClient 不触发 startup,
    避免把真实 LLM_API_KEY 等注入测试进程;已存在环境变量优先,
    容器部署由 compose environment 覆盖。
    """
    load_deploy_env()
    interrupted = _job_store.recover_interrupted()
    if interrupted:
        print(f"[run_api] 服务重启:{len(interrupted)} 个未完成任务已标记为 INTERRUPTED,不自动重跑")


from bdlh_runtime.experiments.public_case_repository import get_case_repository

# 生产用例仓库:data 服务映射(对比用例任务创建时读取;测试注入替身时整体替换本服务)
_public_service = AnonymousJobService(_job_store, case_repository=get_case_repository())

# 私有 CORS：仅 /lab 页面跨端口调用需要。RUN_API_ALLOWED_ORIGINS 为空（默认）时
# 不挂中间件、不带任何 CORS 头（fail-closed）；公开部署永不配置该变量。
_allowed_origins = [origin.strip() for origin in os.getenv("RUN_API_ALLOWED_ORIGINS", "").split(",") if origin.strip()]
if _allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
_JOBS: dict[str, dict[str, Any]] = {}
_BATCH_SLOTS = threading.BoundedSemaphore(max(1, int(os.getenv("MAX_CONCURRENT_BATCHES", "1"))))


def require_login(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    token = _bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail="未提供会话令牌")
    try:
        account = _data().verify_session(token)
    except DataServiceError:
        raise HTTPException(status_code=503, detail="数据服务不可用") from None
    if account is None:
        raise HTTPException(status_code=401, detail="会话无效或已过期")
    return account


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def _data() -> DataClient:
    return DataClient()


class EvalBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_ids: list[str] | None = Field(default=None, max_length=100, description="固定题号子集；空表示全部")
    runs: int = Field(default=1, ge=1, le=5, description="每题每种实现的重复次数")
    include_react: bool = Field(default=True, description="是否包含 LangGraph ReAct 实现")
    model: str = Field(
        default_factory=lambda: os.getenv("LLM_MODEL", "Qwen/Qwen3.6-35B-A3B"),
        min_length=1,
        max_length=100,
        description="模型名；缺省取 LLM_MODEL 环境变量（唯一请求级可配项，base_url 与密钥只在服务端环境变量）",
    )
    max_total_tokens: int | None = Field(
        default=None,
        ge=1,
        description="批次 token 上限(任务四):累计消耗达到后停止发起新运行;缺省取 EVAL_MAX_TOTAL_TOKENS(未设=不限)",
    )
    fixture_set_id: str | None = Field(
        default=None,
        max_length=100,
        description="冻结数据集(GT-2);缺省 ab-eval;负例集 ab-eval-negative-v1,通用集 mock-eval-v1",
    )
    visible_tools: list[str] | None = Field(
        default=None,
        description="工具可见集(GT-4):null=按场景默认;[] 为显式空集(能力缺口实验);元素必须属于工具目录",
    )
    search_top_k: int | None = Field(
        default=None,
        ge=1,
        le=8,
        description="检索装载档 top_k 批次变量(GT-8):设置后固定 search_tools 返回条数;缺省=模型自报(1..8,默认3)",
    )


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class ContextBatchRequest(BaseModel):
    """长上下文压缩对照批次:六套 ctx 用例 × (full-raw / budgeted-comp) 两变体。"""

    model_config = ConfigDict(extra="forbid")

    case_ids: list[str] | None = Field(default=None, max_length=100, description="ctx 用例子集;空表示全部对照变体")
    runs: int = Field(default=1, ge=1, le=5, description="每变体重复次数")
    model: str = Field(
        default_factory=lambda: os.getenv("LLM_MODEL", "Qwen/Qwen3.6-35B-A3B"),
        min_length=1,
        max_length=100,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "run-api"}


@app.get("/ready")
def ready() -> dict[str, Any]:
    try:
        count = len(_data().list_cases())
    except DataServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ready", "case_count": count}


@app.post("/api/v1/login")
def login(request: LoginRequest, http_request: Request) -> dict[str, Any]:
    client_ip = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")
    try:
        result = _data().login(
            username=request.username,
            password=request.password,
            ip_address=client_ip,
            user_agent=user_agent,
        )
    except DataServiceError as exc:
        raise HTTPException(status_code=exc.status_code or 401, detail=str(exc)) from exc
    return {
        "token": result["token"],
        "expires_at": result["expiresAt"],
        # lab 顶栏 whoami 展示用（data 服务 LoginResponse 已含，此前被丢弃）
        "username": str(result.get("username") or ""),
    }


@app.post("/api/v1/logout")
def logout(authorization: str | None = Header(default=None)) -> dict[str, str]:
    token = _bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail="未提供会话令牌")
    try:
        _data().logout(token)
    except DataServiceError:
        raise HTTPException(status_code=503, detail="数据服务不可用") from None
    return {"status": "ok"}


@app.get("/api/v1/cases")
def list_cases(account: Annotated[dict[str, Any], Depends(require_login)]) -> list[dict[str, Any]]:
    try:
        return _data().list_cases()
    except DataServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/v1/tools")
def list_tools(account: Annotated[dict[str, Any], Depends(require_login)]) -> list[dict[str, Any]]:
    """工具目录(/lab 勾选页数据源,GT-4):代理 data 服务目录的 capabilities 段。"""
    try:
        payload = _data().get_tool_catalog()
    except DataServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    tools: list[dict[str, Any]] = []
    for item in payload.get("capabilities") or []:
        tools.append(
            {
                "name": str(item.get("name") or ""),
                "description": str(item.get("description") or ""),
                "domain": str(item.get("domain") or ""),
                "enabled": bool(item.get("enabled", True)),
                # GT-6 评测轴:勾选页高风险红点/写操作类默认不勾的消费字段
                "side_effect": str(item.get("side_effect") or "none"),
                "risk_level": str(item.get("risk_level") or "low"),
            }
        )
    return tools


@app.post("/api/v1/llm-config/test")
def test_llm_config(account: Annotated[dict[str, Any], Depends(require_login)]) -> dict[str, Any]:
    """连通性验证:按服务端 env(deploy/.env / compose / 云 secret)发起一次最小补全。

    LLM 配置不再按账号存储(env 是唯一真源);此端点只做只读探测,不接收配置体。
    """
    base_url = (os.getenv("LLM_BASE_URL") or "").rstrip("/")
    model = os.getenv("LLM_MODEL", "Qwen/Qwen3.6-35B-A3B")
    api_key = os.getenv("LLM_API_KEY") or ""
    if not api_key:
        return {"ok": False, "error": "未配置 API Key(服务端环境变量 LLM_API_KEY)"}
    if not base_url:
        return {"ok": False, "error": "未配置 baseUrl(服务端环境变量 LLM_BASE_URL;env 是唯一真源,无内置默认端点)"}
    ok, detail = _probe_llm(base_url, model, api_key)
    return {"ok": ok, "model": model, "baseUrl": base_url, "detail": detail}


def _probe_llm(base_url: str, model: str, api_key: str) -> tuple[bool, str]:
    """最小连通性调用;错误信息面向页面展示,不含密钥。"""
    import httpx

    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 4},
            timeout=20.0,
        )
    except httpx.HTTPError as exc:
        return False, f"无法连接 {base_url}({type(exc).__name__})"
    if response.status_code == 200:
        return True, "连接成功,模型可用"
    try:
        message = str(response.json().get("error", {}).get("message", response.text[:120]))
    except ValueError:
        message = response.text[:120]
    return False, f"HTTP {response.status_code}: {message}"


@app.post("/api/v1/eval-batches")
def start_eval_batch(
    request: EvalBatchRequest,
    account: Annotated[dict[str, Any], Depends(require_login)],
) -> dict[str, str]:
    data = _data()
    try:
        catalog = data.list_cases()
        known = {str(case["id"]) for case in catalog}
        unknown = [case_id for case_id in request.case_ids or [] if case_id not in known]
        if unknown:
            raise HTTPException(status_code=400, detail=f"未知 case_id：{unknown}")
        _validate_visible_tools(data, request.visible_tools)
        if not _BATCH_SLOTS.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="已有评测批次在运行，请等待完成后再发起")
        batch_id = data.create_batch(
            name=f"Agent 对照 {datetime.now().astimezone().isoformat(timespec='seconds')}",
            fixed_conditions={
                "caseIds": request.case_ids or sorted(known),
                "runsPerCase": request.runs,
                "includeReact": request.include_react,
                "model": request.model,
                "toolData": "frozen",
                # 门槛配置随批次记录(结果在工件 validity_threshold;任务五消费)
                "minValidSamples": int(os.getenv("EVAL_MIN_VALID_SAMPLES", "5")),
                "interleaveSeed": DEFAULT_INTERLEAVE_SEED,
                "maxTotalTokens": _max_total_tokens(request),
                "fixtureSetId": request.fixture_set_id or "ab-eval",
                "visibleTools": request.visible_tools,
                "searchTopK": request.search_top_k,
            },
        )
    except DataServiceError as exc:
        with contextlib.suppress(ValueError):
            _BATCH_SLOTS.release()
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # LLM 配置唯一真源是服务端 env;模型客户端由 runner 内部 build_llm_from_env 构建
    job_id = uuid4().hex[:12]
    job: dict[str, Any] = {
        "job_id": job_id,
        "batch_id": batch_id,
        "status": "running",
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "request": request.model_dump(),
        "report": None,
        "error": None,
        "cancel_requested": False,
    }
    _JOBS[job_id] = job

    def task() -> None:
        try:
            payload, run_records = _execute_eval(request, catalog, job=job)
            _persist_runs(data, batch_id, request, payload, run_records)
            _persist_artifact(batch_id, payload)
            batch_status = "CANCELLED" if payload.get("stop_reason") == "CANCELLED" else "COMPLETE"
            data.complete_batch(batch_id, batch_status)
            job["status"] = "cancelled" if batch_status == "CANCELLED" else "done"
            job["report"] = payload
        except Exception as exc:  # 作业失败进入可见状态，不能让服务进程退出
            with contextlib.suppress(DataServiceError):
                data.complete_batch(batch_id, "FAILED")
            job["status"] = "error"
            job["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            _BATCH_SLOTS.release()

    threading.Thread(target=task, daemon=True).start()
    return {"job_id": job_id, "batch_id": batch_id}


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str, account: Annotated[dict[str, Any], Depends(require_login)]) -> dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="作业不存在；已完成的运行记录请从数据服务读取")
    return job


@app.post("/api/v1/jobs/{job_id}/cancel")
def cancel_job(job_id: str, account: Annotated[dict[str, Any], Depends(require_login)]) -> dict[str, Any]:
    """协作取消(任务四):置停止标志,运行循环在发起新运行前检查;已开始的
    模型调用等待完成,不硬杀。幂等:重复取消与对已结束作业取消均无副作用。"""
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="作业不存在")
    if job["status"] == "running":
        job["cancel_requested"] = True
    return {
        "job_id": job_id,
        "status": job["status"],
        "cancel_requested": bool(job.get("cancel_requested")),
    }


@app.post("/api/v1/context-batches")
def start_context_batch(
    request: ContextBatchRequest,
    account: Annotated[dict[str, Any], Depends(require_login)],
) -> dict[str, str]:
    """长上下文压缩对照:同一 Agent、同一冻结数据,唯一变量是上下文处理策略。"""
    data = _data()
    try:
        views = data.list_cases()
        known = {
            str(view["id"])
            for view in views
            if any(str(item.get("variantId")) in COMPARISON_VARIANTS for item in view.get("variants") or [])
        }
        unknown = [case_id for case_id in request.case_ids or [] if case_id not in known]
        if unknown:
            raise HTTPException(status_code=400, detail=f"未知或非对照用例：{unknown}")
        if not _BATCH_SLOTS.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="已有评测批次在运行，请等待完成后再发起")
        selected = request.case_ids or sorted(known)
        batch_id = data.create_batch(
            name=f"上下文压缩对照 {datetime.now().astimezone().isoformat(timespec='seconds')}",
            fixed_conditions={
                "caseIds": selected,
                "runsPerVariant": request.runs,
                "variants": list(COMPARISON_VARIANTS),
                "model": request.model,
                "toolData": "frozen",
                # 门槛配置随批次记录(结果在工件 validity_threshold;任务五消费)
                "minValidSamples": int(os.getenv("EVAL_MIN_VALID_SAMPLES", "5")),
                "interleaveSeed": DEFAULT_INTERLEAVE_SEED,
                "maxTotalTokens": _max_total_tokens(request),
            },
        )
    except DataServiceError as exc:
        with contextlib.suppress(ValueError):
            _BATCH_SLOTS.release()
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    job_id = uuid4().hex[:12]
    job: dict[str, Any] = {
        "job_id": job_id,
        "batch_id": batch_id,
        "status": "running",
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "request": request.model_dump(),
        "report": None,
        "error": None,
    }
    _JOBS[job_id] = job

    def task() -> None:
        try:
            payload, run_records = _execute_context_eval(request, views, selected)
            _persist_runs(data, batch_id, request, payload, run_records)
            _persist_artifact(batch_id, payload)
            data.complete_batch(batch_id, "COMPLETE")
            job["status"] = "done"
            job["report"] = payload
        except Exception as exc:  # 作业失败进入可见状态，不能让服务进程退出
            with contextlib.suppress(DataServiceError):
                data.complete_batch(batch_id, "FAILED")
            job["status"] = "error"
            job["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            _BATCH_SLOTS.release()

    threading.Thread(target=task, daemon=True).start()
    return {"job_id": job_id, "batch_id": batch_id}


class ContextLinkBatchRequest(BaseModel):
    """联动对照批次:同一长上下文 原始(full-raw)/压缩(budgeted-comp) × 三组实现。"""

    model_config = ConfigDict(extra="forbid")

    case_ids: list[str] | None = Field(default=None, max_length=100, description="ctx 用例子集;空表示全部对照用例")
    runs: int = Field(default=1, ge=1, le=5, description="每格(变体 × 实现)重复次数")
    model: str = Field(
        default_factory=lambda: os.getenv("LLM_MODEL", "Qwen/Qwen3.6-35B-A3B"),
        min_length=1,
        max_length=100,
    )


class ContextCompressRequest(BaseModel):
    """单用例压缩测试:只跑构建器(无模型调用),返回处理报告。"""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=100)
    variant_id: str = Field(default="budgeted-comp", max_length=100, description="取哪个变体的策略与预算")
    token_budget: int | None = Field(default=None, ge=1, description="覆盖预算;缺省取变体预算")


def _context_case_ids(views: list[dict[str, Any]]) -> set[str]:
    return {
        str(view["id"])
        for view in views
        if any(str(item.get("variantId")) in COMPARISON_VARIANTS for item in view.get("variants") or [])
    }


@app.get("/api/v1/context-cases")
def list_context_cases(account: Annotated[dict[str, Any], Depends(require_login)]) -> list[dict[str, Any]]:
    """长上下文库元信息:条目构成 + 保守口径 token 估算(库页列表与压缩测试共用)。"""
    from bdlh_runtime.context.token_count import ConservativeTokenCounter

    counter = ConservativeTokenCounter()
    try:
        views = _data().list_cases()
    except DataServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    out: list[dict[str, Any]] = []
    for view in views:
        variants = [str(item.get("variantId")) for item in view.get("variants") or []]
        if not any(variant in COMPARISON_VARIANTS for variant in variants):
            continue
        case_id = str(view["id"])
        version = int(view.get("version") or 1)
        variant_budgets: dict[str, Any] = {}
        items: list[dict[str, Any]] = []
        for variant_id in COMPARISON_VARIANTS:
            if variant_id not in variants:
                continue
            payload = _data().get_case_variant_context(case_id, version, variant_id)
            rows = payload.get("items") or []
            variant_budgets[variant_id] = {
                "strategy": str(payload.get("contextStrategy") or ""),
                "token_budget": int(payload.get("tokenBudget") or 0),
            }
            if not items:
                items = rows
        counts = {"required": 0, "compressible": 0, "reference_only": 0, "distractor": 0}
        token_total = 0
        for row in items:
            key = str(row.get("classification") or "compressible")
            counts[key if key in counts else "compressible"] += 1
            token_total += counter.count(str(row.get("content") or ""))
        out.append(
            {
                "case_id": case_id,
                "title": str(view.get("title") or ""),
                "message": str(view.get("message") or ""),
                "scene": str(view.get("scene") or ""),
                "authenticated": bool(view.get("authenticated")),
                "item_count": len(items),
                "token_estimate": token_total,
                "item_counts": counts,
                "variants": variant_budgets,
            }
        )
    return out


@app.post("/api/v1/context-compress")
def compress_context_case(
    request: ContextCompressRequest, account: Annotated[dict[str, Any], Depends(require_login)]
) -> dict[str, Any]:
    """单用例现场压缩测试:构建器按变体策略/预算执行一次,返回逐条决策(无模型调用)。"""
    from bdlh_runtime.context import (
        CONSERVATIVE_TOKENIZER_VERSION,
        ContextBuilder,
        ContextBuildRequest,
        ContextStrategy,
    )
    from bdlh_runtime.evaluation.context_eval import (
        _OWNER_ID,
        COMPARISON_VARIANTS,
        fixture_items_to_context_items,
    )

    data = _data()
    try:
        views = data.list_cases()
    except DataServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    known = _context_case_ids(views)
    if request.case_id not in known:
        raise HTTPException(status_code=400, detail=f"未知或非对照用例：{request.case_id}")
    view = next(item for item in views if str(item["id"]) == request.case_id)
    version = int(view.get("version") or 1)
    if request.variant_id not in COMPARISON_VARIANTS:
        raise HTTPException(status_code=400, detail=f"变体必须是 {list(COMPARISON_VARIANTS)} 之一")
    try:
        payload = data.get_case_variant_context(request.case_id, version, request.variant_id)
    except DataServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    strategy = str(payload.get("contextStrategy") or "budgeted")
    budget = request.token_budget or int(payload.get("tokenBudget") or 0)
    items = payload.get("items") or []
    if not items:
        raise HTTPException(status_code=400, detail=f"变体 {request.case_id}/{request.variant_id} 无上下文条目")
    try:
        builder = ContextBuilder()
        built = builder.build(
            ContextBuildRequest(
                items=fixture_items_to_context_items(tuple(items)),
                token_budget=budget,
                strategy=ContextStrategy(strategy),
                owner_id=_OWNER_ID,
            )
        )
    except ValueError as exc:
        return {
            "case_id": request.case_id,
            "variant_id": request.variant_id,
            "strategy": strategy,
            "token_budget": budget,
            "status": "FAILED",
            "error": str(exc),
            "tokenizer_version": CONSERVATIVE_TOKENIZER_VERSION,
        }
    report = built.report
    return {
        "case_id": request.case_id,
        "variant_id": request.variant_id,
        "strategy": strategy,
        "token_budget": report.token_budget,
        "status": "COMPLETE",
        "original_tokens": report.original_tokens,
        "working_tokens": report.working_tokens,
        "required_retained": report.required_retained,
        "tokenizer_version": CONSERVATIVE_TOKENIZER_VERSION,
        "counts": report.counts,
        "warnings": list(report.warnings),
        "decisions": [
            {
                "item_id": decision.item_id,
                "action": decision.action.value,
                "reason": decision.reason,
                "input_tokens": decision.input_tokens,
                "output_tokens": decision.output_tokens,
            }
            for decision in report.decisions
        ],
        "working_excerpt": "\n".join(message.content for message in built.messages)[:2000],
    }


@app.post("/api/v1/context-link-batches")
def start_context_link_batch(
    request: ContextLinkBatchRequest,
    account: Annotated[dict[str, Any], Depends(require_login)],
) -> dict[str, str]:
    """联动对照:同一长上下文 原始/压缩内容分别过三组实现,检验压缩质量。"""
    from bdlh_runtime.evaluation.context_eval import LINKAGE_MODES

    data = _data()
    try:
        views = data.list_cases()
        known = _context_case_ids(views)
        unknown = [case_id for case_id in request.case_ids or [] if case_id not in known]
        if unknown:
            raise HTTPException(status_code=400, detail=f"未知或非对照用例：{unknown}")
        if not _BATCH_SLOTS.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="已有评测批次在运行，请等待完成后再发起")
        selected = request.case_ids or sorted(known)
        batch_id = data.create_batch(
            name=f"上下文联动对照 {datetime.now().astimezone().isoformat(timespec='seconds')}",
            fixed_conditions={
                "caseIds": selected,
                "runsPerCell": request.runs,
                "variants": list(COMPARISON_VARIANTS),
                "agentModes": list(LINKAGE_MODES),
                "model": request.model,
                "toolData": "frozen",
                "minValidSamples": int(os.getenv("EVAL_MIN_VALID_SAMPLES", "5")),
                "interleaveSeed": DEFAULT_INTERLEAVE_SEED,
            },
        )
    except DataServiceError as exc:
        with contextlib.suppress(ValueError):
            _BATCH_SLOTS.release()
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    job_id = uuid4().hex[:12]
    job: dict[str, Any] = {
        "job_id": job_id,
        "batch_id": batch_id,
        "status": "running",
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "request": request.model_dump(),
        "report": None,
        "error": None,
    }
    _JOBS[job_id] = job

    def task() -> None:
        try:
            payload, run_records = _execute_context_link_eval(request, views, selected)
            _persist_runs(data, batch_id, request, payload, run_records)
            _persist_artifact(batch_id, payload)
            data.complete_batch(batch_id, "COMPLETE")
            job["status"] = "done"
            job["report"] = payload
        except Exception as exc:  # 作业失败进入可见状态，不能让服务进程退出
            with contextlib.suppress(DataServiceError):
                data.complete_batch(batch_id, "FAILED")
            job["status"] = "error"
            job["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            _BATCH_SLOTS.release()

    threading.Thread(target=task, daemon=True).start()
    return {"job_id": job_id, "batch_id": batch_id}


def _execute_context_link_eval(
    request: ContextLinkBatchRequest,
    views: list[dict[str, Any]],
    selected: list[str],
) -> tuple[dict[str, Any], list[RunRecord]]:
    from bdlh_runtime.evaluation.context_eval import (
        LINKAGE_MODES,
        load_context_variant_cases,
        run_context_eval,
    )
    from bdlh_runtime.evaluation.context_eval import (
        _report_payload as context_report_payload,
    )

    data = _data()
    cases = [case for case in load_context_variant_cases(views, data) if case.case_id in set(selected)]
    report = asyncio.run(
        run_context_eval(
            cases=cases,
            llm=None,  # runner 内部回落 build_llm_from_env(env 是唯一配置真源)
            model=request.model,
            runs_per_variant=request.runs,
            data=data,
            inter_run_delay_s=float(os.getenv("EVAL_INTER_RUN_DELAY_S", "1")),
            agent_modes=LINKAGE_MODES,
        )
    )
    return context_report_payload(report), report.run_records


@app.get("/api/v1/batches/{batch_id}")
def get_batch(batch_id: str, account: Annotated[dict[str, Any], Depends(require_login)]) -> dict[str, Any]:
    try:
        return _data().get_batch(batch_id)
    except DataServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/v1/runs/{run_id}/detail")
def get_run_detail(run_id: str, account: Annotated[dict[str, Any], Depends(require_login)]) -> dict[str, Any]:
    """单次运行逐步明细:事件流 + 模型/工具/guardrail 明细 + 测量 + 工件登记。"""
    try:
        return _data().get_run_detail(run_id)
    except DataServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ---------------------------------------------------------------------
# 匿名受限测试接口:只接受固定编号与允许的配置字段;匿名结果不可发布
# ---------------------------------------------------------------------


def _anon_token(request: Request, response: Response | None = None) -> str:
    """读取或签发匿名身份 Cookie(原始值只留在浏览器,任务只保存哈希)。"""
    token = request.cookies.get(ANON_COOKIE_NAME) or ""
    if len(token) < 20:
        token = secrets.token_urlsafe(32)
        if response is not None:
            response.set_cookie(
                ANON_COOKIE_NAME,
                token,
                max_age=ANON_COOKIE_MAX_AGE,
                httponly=True,
                samesite="lax",
            )
    return token


@app.get("/api/v1/public/test-options")
def public_test_options(request: Request, response: Response) -> dict[str, Any]:
    """公开测试选项:固定用例/Session 清单 + 服务端固定条件(只读,不创建任务)。"""
    _anon_token(request, response)
    quota = _public_service.quota
    try:
        sessions = public_session_overview()
    except Exception:  # noqa: BLE001 —— Session 数据缺失时保持空列表,不阻塞选项
        sessions = []
    from bdlh_runtime.experiments.public_case_repository import get_case_repository

    try:
        cases = get_case_repository().public_projection()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        cases = []
    return {
        "sessions": sessions,
        "comparison_cases": cases,
        "fixed_conditions": {
            "test_types": ["COMPRESSION_CASE", "COMPARISON_CASE"],
            "agent_mode_ids": list(_AGENT_MODE_IDS),
            "repeat_options": list(quota.repeat_options),
            "compression_repeat_count": 1,
            "max_agent_steps": quota.max_agent_steps,
            "run_counts": {
                "comparison_repeat_3": 9,
                "comparison_repeat_5": 15,
                "compression_session_matrix": 12,
                "compression_all_sessions_theoretical": 36,
            },
        },
        "quota": quota.as_dict(),
    }


@app.post("/api/v1/public/test-jobs")
def create_public_test_job(payload: dict[str, Any], request: Request, response: Response) -> dict[str, Any]:
    """创建匿名测试任务:校验配置并立即返回 job_id;执行在后台进行。

    请求只允许固定编号与配置字段;message/prompt/system_prompt/tool_schema/
    mock_result/model_base_url/api_key 等字段一律拒绝。
    """
    token = _anon_token(request, response)
    try:
        job = _public_service.create_job(payload, anonymous_id_hash=sha256_hex(token))
    except PublicTestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {
        "job_id": job.job_id,
        "status": job.status,
        "unit_count": len(job.units),
        "publishable": job.publishable,
        "custom_conditions": job.custom_conditions,
    }


@app.get("/api/v1/public/test-jobs")
def list_public_test_jobs(request: Request, response: Response) -> list[dict[str, Any]]:
    """我的测试:当前匿名身份的近期任务(进度、已完成单元数、总单元数)。"""
    token = _anon_token(request, response)
    jobs = _job_store.list_for_anonymous(sha256_hex(token), limit=20)
    return [
        {
            "job_id": job.job_id,
            "test_type": job.test_type,
            "execution_scope": job.execution_scope,
            "case_id": job.case_id,
            "session_id": job.session_id,
            "status": job.status,
            "created_at": job.created_at,
            "completed_units": job.completed_unit_count(),
            "total_units": len(job.units),
            "custom_conditions": job.custom_conditions,
        }
        for job in jobs
    ]


@app.get("/api/v1/public/test-jobs/{job_id}")
def get_public_test_job(job_id: str, request: Request, response: Response) -> dict[str, Any]:
    """查看自己任务的状态与摘要(校验匿名身份;他人任务按不存在处理)。"""
    token = _anon_token(request, response)
    try:
        job = _public_service.get_job_for(job_id, sha256_hex(token))
    except PublicTestError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    return job.public_view()


@app.get("/api/v1/public/test-jobs/{job_id}/results")
def get_public_test_results(job_id: str, request: Request, response: Response) -> dict[str, Any]:
    """查看自己任务的公开字段结果(不含内部提示、gold 与未脱敏工具返回)。"""
    token = _anon_token(request, response)
    try:
        job = _public_service.get_job_for(job_id, sha256_hex(token))
    except PublicTestError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    return {"job_id": job.job_id, "status": job.status, "result": job.result, "units": [u.__dict__ for u in job.units]}


@app.post("/api/v1/public/test-jobs/{job_id}/cancel")
def cancel_public_test_job(job_id: str, request: Request, response: Response) -> dict[str, Any]:
    """取消自己的任务:只阻止尚未开始的单元,已产生的运行与费用保留。"""
    token = _anon_token(request, response)
    try:
        job = _public_service.cancel_job(job_id, sha256_hex(token))
    except PublicTestError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    return {
        "job_id": job.job_id,
        "status": job.status,
        "cancel_requested": job.cancel_requested,
        "cancelled_units": sum(1 for unit in job.units if unit.status == "CANCELLED"),
    }


def _execute_eval(
    request: EvalBatchRequest,
    catalog: list[dict[str, Any]],
    job: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[RunRecord]]:
    # LLM 配置唯一真源是服务端 env;llm=None → run_ab_eval 内部 build_llm_from_env
    async def run() -> Any:
        return await run_ab_eval(
            runs_per_case=request.runs,
            model=request.model,
            with_react=request.include_react,
            cases=load_cases(_select_case_views(catalog, request.case_ids)),
            llm=None,
            should_stop=(lambda: bool(job.get("cancel_requested"))) if job is not None else None,
            max_total_tokens=_max_total_tokens(request),
            fixture_set_id=request.fixture_set_id or "ab-eval",
            visible_tools=request.visible_tools,
            search_top_k=request.search_top_k,
            # 低 RPM 档账号的限流缓解:拉大运行间间隔(缺省 1s;环境变量可覆盖)
            inter_run_delay_s=float(os.getenv("EVAL_INTER_RUN_DELAY_S", "1")),
        )

    report = asyncio.run(run())
    return _report_payload(report), report.run_records


def _select_case_views(catalog: list[dict[str, Any]], case_ids: list[str] | None) -> list[dict[str, Any]]:
    """按请求题号过滤执行用例;未指定=全部(仅含带 default 变体的用例)。

    ctx-* 压缩对照用例只有 full-raw/budgeted-comp 变体、无 default 变体,
    属 context-batches 通道,不进编排批次——此前 case_ids 未过滤执行列表,
    目录一旦含无 default 变体的用例,load_cases 即抛"没有 default 变体"。
    """
    if case_ids:
        wanted = set(case_ids)
        return [view for view in catalog if str(view.get("id")) in wanted]
    return [
        view for view in catalog if any(str(item.get("variantId")) == "default" for item in view.get("variants") or [])
    ]


def _max_total_tokens(request: EvalBatchRequest | ContextBatchRequest) -> int | None:
    requested = getattr(request, "max_total_tokens", None)
    if requested is not None:
        return requested
    raw = os.getenv("EVAL_MAX_TOTAL_TOKENS", "").strip()
    return int(raw) if raw.isdigit() else None


def _validate_visible_tools(data: DataClient, visible_tools: list[str] | None) -> None:
    """GT-4 可见集校验:元素必须 ⊆ 工具目录(含 search_tools);未知名 → 400。

    None=按场景默认;[] 是显式空集(能力缺口实验,GT-5 勾选页"全不选"路径),
    与 null 严格区分,不进入比对。
    """
    if not visible_tools:
        return
    try:
        payload = data.get_tool_catalog()
    except DataServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    known = {str(item.get("name")) for item in payload.get("capabilities") or []}
    if "search_tools" in visible_tools:
        known = known | {"search_tools"}
    unknown = [name for name in visible_tools if name not in known]
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知工具名：{sorted(set(unknown))}")


def _execute_context_eval(
    request: ContextBatchRequest,
    views: list[dict[str, Any]],
    selected: list[str],
) -> tuple[dict[str, Any], list[RunRecord]]:
    from bdlh_runtime.evaluation.context_eval import (
        _report_payload as context_report_payload,
    )
    from bdlh_runtime.evaluation.context_eval import (
        load_context_variant_cases,
        run_context_eval,
    )

    data = _data()
    cases = [case for case in load_context_variant_cases(views, data) if case.case_id in set(selected)]
    report = asyncio.run(
        run_context_eval(
            cases=cases,
            llm=None,  # runner 内部回落 build_llm_from_env(env 是唯一配置真源)
            model=request.model,
            runs_per_variant=request.runs,
            data=data,
            inter_run_delay_s=float(os.getenv("EVAL_INTER_RUN_DELAY_S", "1")),
        )
    )
    return context_report_payload(report), report.run_records


def _persist_runs(
    data: DataClient,
    batch_id: str,
    request: EvalBatchRequest | ContextBatchRequest,
    payload: dict[str, Any],
    run_records: list[RunRecord],
) -> None:
    """逐运行落库(任务一):事件流、明细表、测量、统一工件与有效性分类。"""

    run_ids: dict[str, str] = {}
    for record in run_records:
        run_ids[record.run_key] = _persist_one_run(data, batch_id, request, record)
    for row in payload.get("run_records", []):
        run_id = run_ids.get(str(row.get("run_key")))
        if run_id:
            row["run_id"] = run_id


def _persist_one_run(
    data: DataClient, batch_id: str, request: EvalBatchRequest | ContextBatchRequest, record: RunRecord
) -> str:
    run_id = data.create_run(
        {
            "batchId": batch_id,
            "caseId": record.case_id,
            "caseVersion": record.case_version,
            "variantId": record.variant_id,
            "snapshotId": record.snapshot_id,
            "agentMode": record.agent_mode,
            "contextStrategy": record.context_strategy,
            "model": record.model,
            "gitCommit": str(record.provenance.get("git_commit") or os.getenv("GIT_COMMIT", "unknown")),
            "modelConfig": {
                "runs": request.runs,
                "toolData": "frozen",
                "repeatIndex": record.repeat_index,
                "fixtureSetId": getattr(request, "fixture_set_id", None) or "ab-eval",
            },
        }
    )
    record.run_id = run_id
    record.batch_id = batch_id
    if record.events:
        data.save_events(run_id, record.events)
    if record.model_calls:
        data.save_model_calls(run_id, [row.to_payload() for row in record.model_calls])
    if record.tool_calls:
        data.save_tool_calls(run_id, [row.to_payload() for row in record.tool_calls])
    if record.guardrail_checks:
        data.save_guardrail_checks(run_id, [row.to_payload() for row in record.guardrail_checks])
    if record.measurements:
        data.save_measurements(run_id, record.measurements)
    if record.context_build:
        data.save_context_build(run_id, record.context_build)

    status = record.status
    error_category = record.error_category
    artifact = build_run_artifact(record)
    artifact_error: str | None = None
    try:
        storage_ref = _write_run_artifact_file(run_id, artifact)
    except OSError as exc:
        # 工件写失败 → INVALID(架构文档 §7.1):过程可查,但不进能力统计
        status = "INVALID"
        error_category = "ARTIFACT_WRITE_FAILED"
        artifact_error = f"{type(exc).__name__}: {exc}"
        artifact["status"] = status
        artifact["validity"] = validity_of(status)
        artifact["result"]["error_category"] = error_category
        artifact["artifact_hash"] = artifact_hash_of(artifact)
        storage_ref = ""

    valid_run = validity_of(status) == "VALID"
    data.save_evaluation(
        run_id,
        checks=dict(record.judgment),
        metrics=dict(record.measurements),
        valid_run=valid_run,
        status=status,
    )
    if storage_ref and verify_artifact_hash(artifact):
        data.save_artifact(
            run_id,
            artifact_type="run_full",
            storage_ref=storage_ref,
            content_hash=str(artifact["artifact_hash"]),
            public=False,
        )
    data.complete_run(
        run_id,
        {
            "answer_excerpt": record.answer_excerpt[:200],
            "artifact_version": ARTIFACT_VERSION,
            "artifact_hash": artifact.get("artifact_hash"),
            "artifact_error": artifact_error,
            "error_category": error_category,
            "judgment": record.judgment,
        },
        # 真实状态透传:agent_runs.status 与 evaluation_results.status 同源
        status=status,
        error_category=error_category,
    )
    record.status = status
    record.error_category = error_category
    return run_id


def _write_run_artifact_file(run_id: str, artifact: dict[str, Any]) -> str:
    runs_dir = ARTIFACTS_DIR / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    storage_ref = f"runs/{run_id}.json"
    content = json.dumps(artifact, ensure_ascii=False, indent=2)
    (ARTIFACTS_DIR / storage_ref).write_text(content, encoding="utf-8")
    return storage_ref


def _persist_artifact(batch_id: str, payload: dict[str, Any]) -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    (ARTIFACTS_DIR / f"{batch_id}.json").write_text(content, encoding="utf-8")
    (ARTIFACTS_DIR / "latest.json").write_text(content, encoding="utf-8")
