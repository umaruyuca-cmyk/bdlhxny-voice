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
from bdlh_runtime.evaluation.context_eval import COMPARISON_VARIANTS, DEFAULT_INTERLEAVE_SEED
from bdlh_runtime.evaluation.run_telemetry import (
    ARTIFACT_VERSION,
    RunRecord,
    artifact_hash_of,
    build_run_artifact,
    validity_of,
    verify_artifact_hash,
)
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
            experiment_type="context-strategy",
            fixed_conditions=_with_conditions_hash({
                "caseIds": selected,
                "runsPerVariant": request.runs,
                "variants": list(COMPARISON_VARIANTS),
                "model": request.model,
                "toolData": "frozen",
                # 门槛配置随批次记录(结果在工件 validity_threshold;任务五消费)
                "minValidSamples": int(os.getenv("EVAL_MIN_VALID_SAMPLES", "5")),
                "interleaveSeed": DEFAULT_INTERLEAVE_SEED,
                "maxTotalTokens": _max_total_tokens(request),
            }),
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
    _init_job_progress(job, len(selected) * len(COMPARISON_VARIANTS) * request.runs, per_run=False)
    _JOBS[job_id] = job

    def task() -> None:
        try:
            payload, run_records = _execute_context_eval(request, views, selected)
            _persist_runs(data, batch_id, request, payload, run_records)
            _persist_artifact(batch_id, payload)
            data.complete_batch(batch_id, "COMPLETE")
            _finish_job_progress(job)
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


@app.get("/api/v1/batches")
def list_batches(
    limit: int = 20,
    cursor: str | None = None,
    account: Annotated[dict[str, Any], Depends(require_login)] = None,
) -> dict[str, Any]:
    """所有者批次列表(新到旧,分页):模板口径、规模与状态。

    行字段:id / template_id / template_classification / independent_variable /
    repeat_count / variant_count / run_count / status / created_at;
    无模板键的批次对应字段为 null。
    """
    try:
        return _data().list_batches(limit=limit, cursor=cursor)
    except DataServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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
    from bdlh_runtime.experiments.templates import (
        ROLE_ANONYMOUS,
        template_registry_payload,
    )

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
    from bdlh_runtime.experiments import NATIVE_AGENT_MODE_ID, native_context_run_count
    from bdlh_runtime.experiments.templates import tool_exclusion_presets

    return {
        "sessions": sessions,
        "comparison_cases": cases,
        # 实验模板清单(匿名视角):目的、唯一自变量、变体、冻结条件与精确运行数
        "templates": template_registry_payload(role=ROLE_ANONYMOUS),
        # 工具排除预设(版本化常量;tool-availability-degradation 模板的档位下拉)
        "tool_exclusion_presets": [
            {
                "preset_id": preset.preset_id,
                "description": preset.description,
                "excluded_tool_count": len(preset.excluded_tools),
            }
            for preset in tool_exclusion_presets()
        ],
        "fixed_conditions": {
            "test_types": ["COMPRESSION_CASE", "COMPARISON_CASE"],
            # 对比用例统一经实验模板在原生底座上发起
            "agent_mode_ids": [NATIVE_AGENT_MODE_ID],
            "native_agent_mode_id": NATIVE_AGENT_MODE_ID,
            "repeat_options": list(quota.repeat_options),
            "compression_repeat_count": 1,
            "max_agent_steps": quota.max_agent_steps,
            "run_counts": {
                "compression_native_matrix": native_context_run_count(),
            },
        },
        "quota": quota.as_dict(),
    }


@app.get("/api/v1/experiment-templates")
def list_experiment_templates(
    account: Annotated[dict[str, Any], Depends(require_login)],
) -> dict[str, Any]:
    """所有者视角的完整模板清单(含 owner-only 模板与高级设置白名单)。"""
    from bdlh_runtime.experiments.templates import ROLE_OWNER, template_registry_payload

    return template_registry_payload(role=ROLE_OWNER)


class TemplateBatchPlanRequest(BaseModel):
    """模板批次计划请求(预估与发起共用;预估不执行任何运行)。"""

    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1, max_length=100)
    repeat_count: int = Field(ge=1, le=20)
    preset_id: str | None = Field(
        default=None, max_length=100, description="工具排除预设(仅 tool-availability-degradation)"
    )
    variant_labels: list[str] | None = Field(
        default=None, max_length=20, description="模板既有变体的子集;不能上传任意变体"
    )
    context_only: bool = Field(default=False, description="只生成输入不运行(仅上下文模板允许)")
    advanced: dict[str, Any] | None = Field(default=None, description="高级设置;键必须落在模板白名单内")


class TemplateBatchRequest(TemplateBatchPlanRequest):
    """模板批次发起请求:模板作用于固定用例(问题/工具/Mock 来自用例库版本)。"""

    case_id: str = Field(min_length=1, max_length=100)


def _template_model_capability() -> Any:
    """按服务端 env 构建能力描述(不发起网络调用;未配置即视为不支持)。"""
    from bdlh_runtime.infra.llm import capabilities_of, create_llm

    return capabilities_of(create_llm(api_key=os.getenv("LLM_API_KEY")))


def _plan_owner_template_batch(request: TemplateBatchPlanRequest) -> Any:
    from bdlh_runtime.experiments.templates import ROLE_OWNER, TemplatePlanError, plan_template_batch

    try:
        return plan_template_batch(
            request.template_id,
            repeat_count=request.repeat_count,
            role=ROLE_OWNER,
            advanced=request.advanced,
            preset_id=request.preset_id,
            variant_labels=request.variant_labels,
            context_only=request.context_only,
            model_capability=_template_model_capability(),
        )
    except TemplatePlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except ValueError as exc:  # RunConfigError 等(高级字段值非法)
        raise HTTPException(status_code=400, detail=str(exc)) from None


def _template_purpose(template_id: str) -> str:
    from bdlh_runtime.experiments.templates import TemplatePlanError, get_template

    try:
        return get_template(template_id).purpose
    except TemplatePlanError:
        return ""


@app.post("/api/v1/template-batches/plan")
def plan_template_batch_endpoint(
    request: TemplateBatchPlanRequest,
    account: Annotated[dict[str, Any], Depends(require_login)],
) -> dict[str, Any]:
    """模板批次预估:精确运行数、变体配置哈希与冻结条件;不创建任何运行。"""
    plan = _plan_owner_template_batch(request)
    payload = plan.to_payload()
    payload["purpose"] = _template_purpose(plan.template_id)
    return payload


def template_run_model_config(plan: Any, row: dict[str, Any], *, fixture_set_id: str = "") -> dict[str, Any]:
    """模板运行落库载荷(阻断5):模板标识/配置哈希/完整快照进 modelConfig JSONB。

    只构建载荷不执行;data 服务侧新列(template_id/config_hash/per_run_config)
    由增量脚本提供,此处同时把字段冗余进 JSONB,保证现有表也能稳定写入与查询。
    """
    from bdlh_runtime.experiments.templates import EXPERIMENT_DEFINITION_VERSION

    run_config = row.get("run_config") or {}
    return {
        "templateId": plan.template_id,
        "templateVersion": plan.template_version,
        "experimentDefinitionVersion": EXPERIMENT_DEFINITION_VERSION,
        "variantLabel": row.get("variant_label"),
        "repeatIndex": row.get("repeat_index"),
        "configHash": row.get("config_hash") or run_config.get("config_hash"),
        "executionEngine": run_config.get("execution_engine"),
        "governanceProfile": row.get("governance_profile") or run_config.get("governance_profile"),
        "toolDelivery": run_config.get("tool_delivery"),
        "perRunConfig": run_config,
        "toolSchemaHash": row.get("tool_schema_hash"),
        "eligibleCatalogHash": row.get("eligible_catalog_hash"),
        "fixtureSetId": fixture_set_id,
    }


def _execute_template_batch(
    plan: Any, case: Any, *, model: str, llm: Any = None, on_run_done: Any = None
) -> dict[str, Any]:
    """模板批次执行(逐运行构建模型客户端;测试注入 Fake 验证接线,不调真实模型)。

    ``llm=None``(生产):每次运行按各自 RunConfig 生效参数创建独立客户端
    ——温度变体真正携带各自温度,max_output_tokens/parallel_tool_calls 同步生效。
    """
    from bdlh_runtime.experiments.template_runner import run_template_batch

    return asyncio.run(
        run_template_batch(
            plan,
            message=case.message,
            visible_tools=case.allowed_tools,
            llm=llm,
            fixtures=list((case.conditions or {}).get("mock_fixtures") or []),
            fixture_version=str(case.fixture_set_id),
            on_run_done=on_run_done,
        )
    )


def _persist_template_runs(data: DataClient, batch_id: str, plan: Any, case: Any, result: dict[str, Any]) -> None:
    """逐运行落库:模板标识与配置快照进 modelConfig;失败由调用方记入作业错误。"""
    for row in result.get("runs") or []:
        run_id = data.create_run(
            {
                "batchId": batch_id,
                "caseId": case.case_id,
                "caseVersion": case.case_version,
                "variantId": str(row.get("variant_label") or ""),
                "snapshotId": "",
                "agentMode": "native-tool-calling",
                "contextStrategy": str((row.get("run_config") or {}).get("context_strategy") or "full"),
                "model": str(((row.get("run_config") or {}).get("model") or {}).get("model_id") or ""),
                "gitCommit": os.getenv("GIT_COMMIT", "unknown"),
                "modelConfig": template_run_model_config(plan, row, fixture_set_id=str(case.fixture_set_id)),
            }
        )
        data.complete_run(
            run_id,
            {
                "answer_excerpt": str(row.get("answer") or "")[:200],
                "stop_reason": row.get("stop_reason"),
                "actual_agent_steps": row.get("actual_agent_steps"),
                "config_hash": row.get("config_hash"),
            },
            status="COMPLETE" if row.get("validity") == "VALID" else "INVALID",
            error_category=row.get("error"),
        )


def _public_template_case(case_id: str) -> Any:
    from bdlh_runtime.experiments.public_case_repository import get_case_repository

    case = get_case_repository().get_public_case(case_id)
    if case is None:
        raise HTTPException(status_code=400, detail=f"未知或非公开对比用例:{case_id}")
    return case


@app.post("/api/v1/template-batches")
def start_template_batch(
    request: TemplateBatchRequest,
    account: Annotated[dict[str, Any], Depends(require_login)],
) -> dict[str, str]:
    """所有者按模板发起批次:固定用例 × 模板变体,统一原生底座执行。

    上下文类模板(context-strategy-comparison)不在此入口——它作用于压缩
    Session,请使用压缩用例的「原生 4×1」入口。
    """
    from bdlh_runtime.experiments.templates import CLASSIFICATION_FORMAL, TemplatePlanError, get_template

    try:
        template = get_template(request.template_id)
    except TemplatePlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if template.classification != CLASSIFICATION_FORMAL:
        raise HTTPException(
            status_code=400,
            detail="该模板分类不支持从模板入口发起;请选择正式单变量模板",
        )
    if "COMPARISON_CASE" not in template.allowed_test_types:
        raise HTTPException(
            status_code=400,
            detail="该模板不作用于对比用例;上下文模板请使用压缩用例的「原生 4×1」入口",
        )
    if request.context_only:
        raise HTTPException(status_code=400, detail="发起接口不接受 context_only;预估请用 /template-batches/plan")
    case = _public_template_case(request.case_id)
    plan = _plan_owner_template_batch(request)
    model = os.getenv("LLM_MODEL", "Qwen/Qwen3.6-35B-A3B")
    data = _data()
    if not _BATCH_SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="已有评测批次在运行，请等待完成后再发起")
    try:
        conditions = {
            **plan.fixed_conditions,
            "case_id": case.case_id,
            "case_version": case.case_version,
            "model": model,
            "fixture_set_id": str(case.fixture_set_id),
            "template_plan_hash": plan.fixed_conditions_hash,
        }
        batch_id = data.create_batch(
            name=f"模板实验 {plan.template_id} {datetime.now().astimezone().isoformat(timespec='seconds')}",
            experiment_type=f"template:{plan.template_id}",
            fixed_conditions=_with_conditions_hash(conditions),
        )
    except DataServiceError as exc:
        with contextlib.suppress(ValueError):
            _BATCH_SLOTS.release()
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    job_id = uuid4().hex[:12]
    job: dict[str, Any] = {
        "job_id": job_id,
        "batch_id": batch_id,
        "template_id": plan.template_id,
        "classification": plan.classification,
        "status": "running",
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "request": request.model_dump(),
        "report": None,
        "error": None,
        "cancel_requested": False,
    }
    _init_job_progress(job, plan.run_count, per_run=True)
    _JOBS[job_id] = job

    def task() -> None:
        def bump_progress(row: dict[str, Any]) -> None:
            progress = job.get("progress") or {}
            progress["done"] = int(progress.get("done") or 0) + 1
            repeat_no = int(row.get("repeat_index") or 0) + 1
            progress["current"] = f"{row.get('variant_label')} · 第{repeat_no}次"

        try:
            report = _execute_template_batch(plan, case, model=model, on_run_done=bump_progress)
            _persist_template_runs(data, batch_id, plan, case, report)
            _persist_artifact(batch_id, report)
            data.complete_batch(batch_id, "COMPLETE")
            _finish_job_progress(job)
            job["status"] = "done"
            job["report"] = report
        except Exception as exc:  # noqa: BLE001 —— 作业失败进入可见状态,不能让服务进程退出
            with contextlib.suppress(DataServiceError):
                data.complete_batch(batch_id, "FAILED")
            job["status"] = "error"
            job["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            _BATCH_SLOTS.release()

    threading.Thread(target=task, daemon=True).start()
    return {
        "job_id": job_id,
        "batch_id": batch_id,
        "template_id": plan.template_id,
        "classification": plan.classification,
        "formal": str(plan.classification == CLASSIFICATION_FORMAL).lower(),
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


def _max_total_tokens(request: ContextBatchRequest) -> int | None:
    requested = getattr(request, "max_total_tokens", None)
    if requested is not None:
        return requested
    raw = os.getenv("EVAL_MAX_TOTAL_TOKENS", "").strip()
    return int(raw) if raw.isdigit() else None


def _with_conditions_hash(conditions: dict[str, Any]) -> dict[str, Any]:
    """批次固定条件附加规范化哈希(阶段A3):哈希覆盖除自身外的全部字段。"""
    from bdlh_runtime.experiments.run_config import hash_of

    return {**conditions, "fixed_conditions_hash": hash_of(conditions)}


def _init_job_progress(job: dict[str, Any], total: int, *, per_run: bool) -> None:
    """作业进度字段:total=精确运行数;per_run 的模板批次逐运行更新 done/current,
    旧入口 runner 无逐运行回调,done 保持 None(完成后一次性置满)。"""
    job["progress"] = {"total": int(total), "done": 0 if per_run else None, "current": ""}


def _finish_job_progress(job: dict[str, Any]) -> None:
    progress = job.get("progress")
    if progress is not None:
        progress["done"] = progress["total"]
        progress["current"] = ""


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
    request: ContextBatchRequest,
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
    data: DataClient, batch_id: str, request: ContextBatchRequest, record: RunRecord
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
                "fixtureSetId": "ab-eval",
                # 运行配置快照哈希(阶段A3;配置体在工件 provenance.per_run_config)
                "configHash": record.provenance.get("config_hash") or None,
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
