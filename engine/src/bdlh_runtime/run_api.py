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
from fastapi.responses import FileResponse
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
from bdlh_runtime.experiments.series_runner import SeriesRunError, execute_series_run
from bdlh_runtime.experiments.series_store import (
    DbSeriesStore,
    SeriesConflictError,
    SeriesIdempotencyConflict,
    SeriesRecord,
    run_entry_view,
)
from bdlh_runtime.experiments.public_service import (
    AnonymousJobService,
    IdempotencyConflict,
    PublicTestError,
    _request_hash,
)
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
    audited = _job_store.audit_invalid_agent_runs()
    if audited:
        print(f"[run_api] 历史审计:{len(audited)} 个任务含无 Agent 模型调用证据的单元,"
              f"已标记 INVALID/LLM_UNAVAILABLE(原记录保留)")
    try:
        orphans = _fail_orphan_batches(_data())
        if orphans:
            print(f"[run_api] 服务重启:{orphans} 个执行中的批次随上一进程中断,已标记为 FAILED(不会自愈,请重新发起)")
    except Exception as exc:  # noqa: BLE001 —— data 不可达时不阻塞启动
        print(f"[run_api] 孤儿批次清点跳过:{exc}")


from bdlh_runtime.experiments.public_case_repository import get_case_repository

# 生产用例仓库:data 服务映射(对比用例任务创建时读取;测试注入替身时整体替换本服务)
_public_service = AnonymousJobService(_job_store, case_repository=get_case_repository())

# 可选 CORS(默认关闭):前端标准形态为同源反代,不需要跨端口调用;
# RUN_API_ALLOWED_ORIGINS 为空时不挂中间件、不带任何 CORS 头(fail-closed)。
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

# 所有者批次幂等(P0-4):account_id + idempotency_key → (request_hash, 响应)。
# 单实例部署,内存表即可保证"查重→创建"原子;数据库唯一约束由增量脚本提供。
_IDEMPOTENCY_LOCK = threading.Lock()
_IDEMPOTENT_RESPONSES: dict[str, tuple[str, dict[str, Any]]] = {}


def _account_id(account: dict[str, Any]) -> str:
    return str(account.get("accountId") or account.get("username") or "")


def _check_owner_idempotency(account: dict[str, Any], request: BaseModel) -> dict[str, Any] | None:
    """所有者批次幂等查重:同键同请求体 → 返回首次响应;同键不同请求体 → 409。"""
    key = str(getattr(request, "idempotency_key", "") or "").strip()
    if not key:
        return None
    body = request.model_dump(exclude={"idempotency_key"})
    with _IDEMPOTENCY_LOCK:
        stored = _IDEMPOTENT_RESPONSES.get(f"{_account_id(account)}:{key}")
        if stored is None:
            return None
        request_hash, response = stored
        if request_hash != _request_hash(body):
            raise HTTPException(
                status_code=409,
                detail="幂等键冲突:该键已被不同参数的请求使用,请修改配置后使用新键重试",
            )
        return dict(response)


def _remember_owner_idempotency(account: dict[str, Any], request: BaseModel, response: dict[str, Any]) -> None:
    key = str(getattr(request, "idempotency_key", "") or "").strip()
    if not key:
        return
    body = request.model_dump(exclude={"idempotency_key"})
    with _IDEMPOTENCY_LOCK:
        _IDEMPOTENT_RESPONSES[f"{_account_id(account)}:{key}"] = (_request_hash(body), dict(response))


def _fail_orphan_batches(data: DataClient, *, limit: int = 50) -> int:
    """把 data 服务里仍处 RUNNING 的批次标记 FAILED(单实例部署:上一进程
    执行中的批次随进程死亡,不会自愈;诚实标记而非永远挂起)。返回清理数量。"""
    rows = (data.list_batches(limit=limit).get("batches") or [])
    orphans = [row for row in rows if str(row.get("status")) == "RUNNING"]
    for row in orphans:
        data.complete_batch(str(row["id"]), "FAILED")
    return len(orphans)


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
    idempotency_key: str | None = Field(
        default=None, min_length=8, max_length=128,
        description="提交幂等键;同键同请求体的重试返回原批次,不同请求体返回 409",
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


@app.get("/api/v1/jobs/by-batch/{batch_id}")
def get_job_by_batch(batch_id: str, account: Annotated[dict[str, Any], Depends(require_login)]) -> dict[str, Any]:
    """按批次号找回内存作业(进度/报告);服务重启后按不存在处理,运行记录走数据服务。"""
    matches = [job for job in _JOBS.values() if job.get("batch_id") == batch_id]
    if not matches:
        raise HTTPException(status_code=404, detail="批次无关联作业(已完成较久或服务已重启)")
    matches.sort(key=lambda j: str(j.get("started_at") or ""))
    return matches[-1]


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
    replay = _check_owner_idempotency(account, request)
    if replay is not None:
        return replay
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
            _save_batch_report_best_effort(data, batch_id, payload)
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
    response = {"job_id": job_id, "batch_id": batch_id}
    _remember_owner_idempotency(account, request, response)
    return response


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
    except Exception as exc:  # noqa: BLE001 —— data 400(如误传任务号)按不存在处理,不炸 500
        raise HTTPException(status_code=404, detail="批次不存在或标识无效") from exc


def _load_batch_report(batch_id: str) -> dict[str, Any] | None:
    """批次报告读取:数据服务 report 列优先,本地工件兜底;不存在返回 None。"""
    try:
        from_db = _data().get_batch_report(batch_id)
        if from_db:
            return from_db
    except Exception as exc:  # noqa: BLE001 —— 报告读取不因 data 不可达而失败,走磁盘兜底
        print(f"[run_api] 批次报告读库失败,回退本地工件:{exc}")
    path = ARTIFACTS_DIR / f"{batch_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/v1/batches/{batch_id}/report")
def get_batch_report(batch_id: str, account: Annotated[dict[str, Any], Depends(require_login)]) -> dict[str, Any]:
    """批次执行报告(磁盘工件):内存作业随服务重启清除后,报告的持久来源。

    返回执行器落盘的完整 payload(含 compression_details/by_variant/stats);
    工件不存在(批次未完成或较早日志批次)按 404 处理。
    """
    report = _load_batch_report(batch_id)
    if report is None:
        raise HTTPException(status_code=404, detail="批次报告不存在(未完成,且无本地工件)")
    return report


@app.get("/api/v1/statistics/batches/{batch_id}")
def get_batch_statistics(batch_id: str, account: Annotated[dict[str, Any], Depends(require_login)]) -> dict[str, Any]:
    """实验组累计统计快照(P0-7):纯代码从原始运行记录重算,不产生任何 LLM 请求。

    原始运行记录是事实真源,统计快照是可重建的派生数据;
    每次请求全量重算,展示口径永远与源数据一致。
    """
    report = _load_batch_report(batch_id)
    if report is None:
        raise HTTPException(status_code=404, detail="批次报告不存在,无法生成统计快照")
    from bdlh_runtime.statistics import build_snapshot

    return build_snapshot(batch_id, report=report)


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
    """公开测试选项:固定用例/Session 清单 + 服务端固定条件(只读,不创建任务)。

    模板清单返回全量注册表(带 anonymous_allowed 标记):匿名可见全部模板,
    仅登录所有者可发起的模板由前端渲染为灰色锁定卡;能否真正发起仍由
    plan_template_batch 在创建批次时按角色校验,接口下发不构成权限。
    """
    from bdlh_runtime.experiments.templates import template_registry_payload

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
        # 实验模板清单(全量注册表;匿名仅可发起 anonymous_allowed=true 的子集)
        "templates": template_registry_payload(),
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
        # 调用上限说明(§11.3):发起前展示;是上限口径,不冒充实际费用
        "call_limits": {
            "summary_max_calls_per_build": _summary_max_calls(),
            "max_llm_requests_per_job": _env_limit_int("MAX_LLM_REQUESTS_PER_JOB"),
            "max_input_tokens_per_job": _env_limit_int("MAX_INPUT_TOKENS_PER_JOB"),
            "max_estimated_cost_per_job": _env_limit_float("MAX_ESTIMATED_COST_PER_JOB"),
        },
    }


def _summary_max_calls() -> int:
    from bdlh_runtime.session.llm_summary import LLMSummarizer

    raw = (os.getenv("LLM_SUMMARY_MAX_CALLS_PER_BUILD") or "").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return LLMSummarizer.MAX_CALLS_PER_BUILD_DEFAULT


def _env_limit_int(name: str, *, fallback: int = 0) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        return int(raw)
    except ValueError:
        return fallback


def _env_limit_float(name: str) -> float:
    raw = (os.getenv(name) or "").strip()
    try:
        value = float(raw)
        return value if value > 0 else 0.0
    except ValueError:
        return 0.0


@app.get("/api/v1/public/test-jobs/{job_id}/context-artifacts/{variant_id}")
def download_context_artifact(job_id: str, variant_id: str, request: Request, response: Response) -> FileResponse:
    """下载本人任务的上下文工件(四方式之一);匿名身份隔离,他人任务按不存在处理。"""
    from bdlh_runtime.experiments import CONTEXT_MODES
    from bdlh_runtime.experiments.compression import session_case_dir

    token = _anon_token(request, response)
    try:
        job = _public_service.get_job_for(job_id, sha256_hex(token))
    except PublicTestError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    if variant_id not in CONTEXT_MODES or not job.session_id:
        raise HTTPException(status_code=404, detail="工件不存在")
    path = session_case_dir(job.session_id) / "compiled" / f"{variant_id}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="工件尚未生成:先执行「生成四份上下文」操作")
    return FileResponse(path, media_type="application/json", filename=f"{job.session_id}-{variant_id}.json")


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
    session_id: str | None = Field(default=None, max_length=100, description="压缩类模板作用于的 Session 编号")
    advanced: dict[str, Any] | None = Field(default=None, description="高级设置;键必须落在模板白名单内")
    idempotency_key: str | None = Field(
        default=None, min_length=8, max_length=128,
        description="提交幂等键;同键同请求体的重试返回原批次,不同请求体返回 409",
    )


class TemplateBatchRequest(TemplateBatchPlanRequest):
    """模板批次发起请求:对比模板作用于固定用例;压缩类模板作用于 Session。"""

    case_id: str = Field(default="", max_length=100)


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
    # agent_runs 对 (case,version,variant) 与 snapshot_id 有外键:只能引用
    # case_variants/data_snapshots 已注册行;模板自变量(温度等)记录在
    # modelConfig.variantLabel,不进 variant_id。
    registered = next(
        (v for v in (case.conditions.get("case_variants") or []) if v.get("snapshot_id")),
        None,
    )
    for row in result.get("runs") or []:
        run_id = data.create_run(
            {
                "batchId": batch_id,
                "caseId": case.case_id,
                "caseVersion": case.case_version,
                "variantId": str(registered["variant_id"]) if registered else "default",
                "snapshotId": str(registered["snapshot_id"]) if registered else f"{case.case_id}:default:{case.fixture_set_id}",
                "agentMode": "native-tool-calling",
                "contextStrategy": str((row.get("run_config") or {}).get("context_strategy") or "full"),
                "model": str(((row.get("run_config") or {}).get("model") or {}).get("model_id") or ""),
                "gitCommit": os.getenv("GIT_COMMIT", "unknown"),
                "modelConfig": {
                    **template_run_model_config(plan, row, fixture_set_id=str(case.fixture_set_id)),
                    # 实际生效参数(逐运行模型实例属性回读;请求值见 perRunConfig.model)
                    "appliedModelParams": row.get("applied_model_params") or {},
                },
            }
        )
        model_calls = row.get("model_calls") or []
        if model_calls:
            # Token 计量落库(11.1):逐请求摘要行 + 汇总测量;账单口径来自
            # 响应 usage,本地估算行随 NativeRunRecord.tokens_estimated 可辨
            data.save_model_calls(run_id, model_calls)
            data.save_measurements(
                run_id,
                {
                    "llmMs": sum(int(call.get("durationMs") or 0) for call in model_calls),
                    "totalDurationMs": int(row.get("duration_ms") or 0),
                    "promptTokens": int(row.get("input_tokens") or 0),
                    "completionTokens": int(row.get("output_tokens") or 0),
                },
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


def _persist_series_run(data: DataClient, series: SeriesRecord, payload: dict[str, Any]) -> None:
    """实验组单次运行落库(agent_runs):与批次运行同一张表、同一查询口径。

    实验组状态文档(报告列)已有正本;此处尽力而为,失败只记日志、
    不回滚实验组登记。压缩用例的 caseId=Session 编号,与压缩对照批次一致。
    """
    from bdlh_runtime.experiments.templates import EXPERIMENT_DEFINITION_VERSION, get_template

    template = get_template(series.template_id)
    is_compression = "COMPRESSION_CASE" in template.allowed_test_types
    run_config = payload.get("run_config") or {}
    model_config = {
        "templateId": series.template_id,
        "templateVersion": series.template_version,
        "experimentDefinitionVersion": EXPERIMENT_DEFINITION_VERSION,
        "seriesId": series.series_id,
        "variantLabel": payload.get("variant_label"),
        "repeatIndex": payload.get("repeat_index"),
        "configHash": payload.get("config_hash"),
        "appliedModelParams": payload.get("applied_model_params") or {},
    }
    if is_compression:
        case_id = series.case_id
        case_version = 1
        variant_id = str(payload.get("variant_label") or "default")
        snapshot_id = f"{case_id}:default"
    else:
        case = _public_template_case(series.case_id)
        registered = next(
            (v for v in (case.conditions.get("case_variants") or []) if v.get("snapshot_id")),
            None,
        )
        case_id = case.case_id
        case_version = int(case.case_version)
        variant_id = str(registered["variant_id"]) if registered else "default"
        snapshot_id = str(registered["snapshot_id"]) if registered else f"{case.case_id}:default:{case.fixture_set_id}"
        model_config["fixtureSetId"] = str(case.fixture_set_id)
    run_id = data.create_run(
        {
            "batchId": series.series_id,
            "caseId": case_id,
            "caseVersion": case_version,
            "variantId": variant_id,
            "snapshotId": snapshot_id,
            "agentMode": "native-tool-calling",
            "contextStrategy": str(run_config.get("context_strategy") or "full"),
            "model": str((run_config.get("model") or {}).get("model_id") or "configured-model"),
            "gitCommit": os.getenv("GIT_COMMIT", "unknown"),
            "modelConfig": model_config,
        }
    )
    model_calls = payload.get("model_calls") or []
    if model_calls:
        data.save_model_calls(run_id, model_calls)
        data.save_measurements(
            run_id,
            {
                "llmMs": sum(int(call.get("durationMs") or 0) for call in model_calls),
                "totalDurationMs": int(payload.get("duration_ms") or 0),
                "promptTokens": int(payload.get("input_tokens") or 0),
                "completionTokens": int(payload.get("output_tokens") or 0),
            },
        )
    data.complete_run(
        run_id,
        {
            "answer_excerpt": str(payload.get("answer") or "")[:200],
            "stop_reason": payload.get("stop_reason"),
            "actual_agent_steps": payload.get("actual_agent_steps"),
            "config_hash": payload.get("config_hash"),
        },
        status="COMPLETE" if payload.get("validity") == "VALID" else "INVALID",
        error_category=payload.get("error"),
    )


def _public_template_case(case_id: str) -> Any:
    from bdlh_runtime.experiments.public_case_repository import get_case_repository

    case = get_case_repository().get_public_case(case_id)
    if case is None:
        raise HTTPException(status_code=400, detail=f"未知或非公开对比用例:{case_id}")
    return case


def _persist_comparison_runs(data: DataClient, batch_id: str, session_id: str, result: dict[str, Any]) -> None:
    """压缩方法对照逐运行落库:caseId=Session 编号,method 进 variantId 与 contextStrategy。"""
    run_configs = result.get("run_configs") or {}
    for row in result.get("cells") or []:
        unit_id = str(row.get("unit_id") or "")
        run_id = data.create_run(
            {
                "batchId": batch_id,
                "caseId": session_id,
                "caseVersion": int(result.get("session_version") or 1),
                "variantId": str(row.get("context_variant") or ""),
                # data 侧 @NotBlank;对齐 case:变体:版本 约定
                "snapshotId": f"{session_id}:{row.get('context_variant')}:v{result.get('session_version') or 1}",
                "agentMode": str(row.get("agent_mode_id") or "native-tool-calling"),
                "contextStrategy": str(row.get("context_variant") or ""),
                "model": os.getenv("LLM_MODEL", ""),
                "gitCommit": os.getenv("GIT_COMMIT", "unknown"),
                "modelConfig": {
                    "unitId": unit_id,
                    "perRunConfig": run_configs.get(unit_id),
                    "contextArtifactHash": row.get("context_artifact_hash"),
                },
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


def _start_compression_method_batch(
    request: TemplateBatchRequest, template: Any, *, account: dict[str, Any]
) -> dict[str, str]:
    """压缩方法对照批次(仅私有台):抽取式 vs LLM 生成式,同模型同目标 token。

    - context_only=true:只生成两种压缩上下文(摘要 LLM 按需真实调用,0 个 Agent 运行);
    - 否则:两种上下文各自运行同一次 Agent(2 个运行),逐运行落库并写批次工件。
    """
    import asyncio as _asyncio

    from bdlh_runtime.experiments.compression import (
        COMPRESSION_SESSIONS,
        generate_compression_method_contexts,
        run_compression_method_comparison,
    )
    from bdlh_runtime.experiments.templates import (
        ROLE_OWNER,
        TemplatePlanError,
        plan_template_batch,
    )

    session_id = str(request.session_id or "")
    replay = _check_owner_idempotency(account, request)
    if replay is not None:
        return replay
    known_sessions = [row[0] for row in COMPRESSION_SESSIONS]
    if session_id not in known_sessions:
        raise HTTPException(status_code=400, detail=f"未知压缩 Session:{session_id!r};可用:{known_sessions}")
    try:
        plan = plan_template_batch(
            template.template_id, repeat_count=1, role=ROLE_OWNER, context_only=bool(request.context_only)
        )
    except TemplatePlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    model = os.getenv("LLM_MODEL", "Qwen/Qwen3.6-35B-A3B")
    data = _data()
    if not _BATCH_SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="已有评测批次在运行，请等待完成后再发起")
    run_count = 0 if request.context_only else plan.run_count
    try:
        from bdlh_runtime.experiments.run_config import RunConfig

        conditions = {
            **plan.fixed_conditions,
            "session_id": session_id,
            "model": model,
            "context_only": bool(request.context_only),
            "template_plan_hash": plan.fixed_conditions_hash,
            # 冻结配置快照(批次无逐运行落库时,参数对照表的数据来源)
            "frozen_run_config": RunConfig().to_payload(),
        }
        batch_id = data.create_batch(
            name=f"压缩方法对照 {session_id} {datetime.now().astimezone().isoformat(timespec='seconds')}",
            experiment_type=f"template:{template.template_id}",
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
        "template_id": template.template_id,
        "classification": template.classification,
        "status": "running",
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "request": request.model_dump(),
        "report": None,
        "error": None,
        "cancel_requested": False,
    }
    _init_job_progress(job, run_count, per_run=True)
    _JOBS[job_id] = job

    def note_phase(text: str) -> None:
        """作业进度 phase:当前正在执行的步骤(编译/LLM 摘要/逐单元运行),前端实时展示。"""
        progress = job.get("progress") or {}
        progress["phase"] = text
        job["progress"] = progress

    def task() -> None:
        try:
            def bump_cell(row: dict[str, Any]) -> None:
                progress = job.get("progress") or {}
                progress["done"] = int(progress.get("done") or 0) + 1
                progress["current"] = f"{row.get('context_variant')} · 第{(row.get('repeat_index') or 0) + 1}次"
                job["progress"] = progress

            if request.context_only:
                payload = generate_compression_method_contexts(
                    session_id,
                    on_phase=note_phase,
                    should_stop=lambda: bool(job.get("cancel_requested")),
                )
            else:
                payload = _asyncio.run(
                    run_compression_method_comparison(
                        session_id,
                        max_agent_steps=_public_service.quota.max_agent_steps,
                        on_cell_done=bump_cell,
                        on_phase=note_phase,
                    )
                )
                _persist_comparison_runs(data, batch_id, session_id, payload)
            _persist_artifact(batch_id, payload)
            data.complete_batch(batch_id, "COMPLETE")
            _save_batch_report_best_effort(data, batch_id, payload)
            _finish_job_progress(job)
            job["status"] = "done"
            job["report"] = payload
        except Exception as exc:  # noqa: BLE001 —— 作业失败进入可见状态,不能让服务进程退出
            with contextlib.suppress(DataServiceError):
                data.complete_batch(batch_id, "FAILED")
            job["status"] = "error"
            job["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            _BATCH_SLOTS.release()

    threading.Thread(target=task, daemon=True).start()
    response = {
        "job_id": job_id,
        "batch_id": batch_id,
        "template_id": template.template_id,
        "classification": template.classification,
        "formal": "true",
    }
    _remember_owner_idempotency(account, request, response)
    return response


@app.post("/api/v1/template-batches")
def start_template_batch(
    request: TemplateBatchRequest,
    account: Annotated[dict[str, Any], Depends(require_login)],
) -> dict[str, str]:
    """旧模板批次入口(P0-7 13.13 已退役,保留压缩方法对照兼容)。

    一次请求隐式展开成 4/8/12/20 个 Agent 运行的路径一律 410;
    报告/批次/统计读取与预估接口保留。仅保留 compression-method-comparison:
    固定 2 单元、repeat_count 强制为 1,无重复次数乘法,待实验组支持
    压缩用例后再迁移。上下文类模板不在此入口(压缩用例「原生 4×1」入口)。
    """
    from bdlh_runtime.experiments.templates import CLASSIFICATION_FORMAL, TemplatePlanError, get_template

    try:
        template = get_template(request.template_id)
    except TemplatePlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if request.template_id != "compression-method-comparison":
        raise HTTPException(
            status_code=410,
            detail="模板批次发起已退役(方案 13.13):一次请求只创建一个 Agent 运行。"
            "请改用实验组接口:POST /api/v1/experiment-series 创建实验组,"
            "再 POST /api/v1/experiment-series/{series_id}/runs 逐个追加样本;"
            "预估(/template-batches/plan)与报告读取接口保留。",
        )
    if not request.context_only:
        # 压缩方法对照的 Agent 运行已迁移实验组:两方法逐样本单请求;
        # 仅「生成上下文工件」(context_only,0 个 Agent 运行)保留本入口
        raise HTTPException(
            status_code=410,
            detail="压缩方法对照的 Agent 运行已迁移实验组(方案 13.13):"
            "POST /api/v1/experiment-series {template_id, session_id} 创建实验组,"
            "再 POST /api/v1/experiment-series/{series_id}/runs 逐个运行各压缩方法;"
            "仅「生成上下文工件(context_only)」保留本入口(0 个 Agent 运行)。",
        )
    if template.classification != CLASSIFICATION_FORMAL:
        raise HTTPException(
            status_code=400,
            detail="该模板分类不支持从模板入口发起;请选择正式单变量模板",
        )
    if template.template_id == "compression-method-comparison":
        return _start_compression_method_batch(request, template, account=account)
    if "COMPARISON_CASE" not in template.allowed_test_types:
        raise HTTPException(
            status_code=400,
            detail="该模板不作用于对比用例;上下文模板请使用压缩用例的「原生 4×1」入口",
        )
    if request.context_only:
        raise HTTPException(status_code=400, detail="发起接口不接受 context_only;预估请用 /template-batches/plan")
    case = _public_template_case(request.case_id)
    replay = _check_owner_idempotency(account, request)
    if replay is not None:
        return replay
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
            _save_batch_report_best_effort(data, batch_id, report)
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
    response = {
        "job_id": job_id,
        "batch_id": batch_id,
        "template_id": plan.template_id,
        "classification": plan.classification,
        "formal": str(plan.classification == CLASSIFICATION_FORMAL).lower(),
    }
    _remember_owner_idempotency(account, request, response)
    return response


# ---------------------------------------------------------------------
# 实验组与单次运行(P0-7 13.3–13.5):一次提交只创建一个 Agent 运行,
# 数据分析由统计模块从独立 Run 重建,实验组只负责逻辑分组与样本积累。


class ExperimentSeriesCreateRequest(BaseModel):
    """创建实验组:只保存定义与冻结条件,不运行任何 Agent。"""

    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1, max_length=100)
    case_id: str = Field(default="", max_length=100)
    session_id: str | None = Field(
        default=None, max_length=100,
        description="压缩类模板(compression-method-comparison)作用于的 Session 编号",
    )
    variant_labels: list[str] | None = Field(
        default=None, max_length=20, description="模板既有变体的子集;缺省为全部变体"
    )
    preset_id: str | None = Field(default=None, max_length=100)
    advanced: dict[str, Any] | None = Field(default=None)


class SeriesRunRequest(BaseModel):
    """单次运行请求:一个变体 + 幂等键;repeat_count/变体数组一律拒绝。"""

    model_config = ConfigDict(extra="forbid")

    variant_id: str = Field(min_length=1, max_length=100)
    idempotency_key: str | None = Field(
        default=None, min_length=8, max_length=128,
        description="同键同请求体重试返回原运行;同键不同变体返回 409",
    )


_SERIES_STORE = DbSeriesStore(lambda: _data())  # 数据库是唯一事实真源;文件版仅测试/离线迁移使用


def _series_run_entry_view(entry: dict[str, Any] | None, series_id: str) -> dict[str, Any]:
    return run_entry_view(entry or {}, series_id=series_id)


@app.post("/api/v1/experiment-series", status_code=201)
def create_experiment_series(
    request: ExperimentSeriesCreateRequest,
    account: Annotated[dict[str, Any], Depends(require_login)],
) -> dict[str, Any]:
    """创建实验组(方案 13.4):冻结模板定义与用例,不创建任何运行单元。"""
    from bdlh_runtime.experiments.templates import (
        CLASSIFICATION_FORMAL,
        ROLE_OWNER,
        TemplatePlanError,
        get_template,
        plan_template_batch,
    )

    try:
        template = get_template(request.template_id)
    except TemplatePlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if template.classification != CLASSIFICATION_FORMAL or not (
        "COMPARISON_CASE" in template.allowed_test_types
        or "COMPRESSION_CASE" in template.allowed_test_types
    ):
        raise HTTPException(
            status_code=400,
            detail="实验组目前只支持正式单变量模板(对比用例或压缩用例)",
        )
    compression_session = "COMPRESSION_CASE" in template.allowed_test_types
    if compression_session:
        from bdlh_runtime.experiments.compression import COMPRESSION_SESSIONS

        known_sessions = [row[0] for row in COMPRESSION_SESSIONS]
        if str(request.session_id or "") not in known_sessions:
            raise HTTPException(
                status_code=400,
                detail=f"未知压缩 Session:{request.session_id!r};可用:{known_sessions}",
            )
        case_ref = str(request.session_id)
    else:
        case_ref = _public_template_case(request.case_id).case_id
    try:
        plan = plan_template_batch(
            request.template_id,
            repeat_count=1,
            role=ROLE_OWNER,
            advanced=request.advanced,
            preset_id=request.preset_id,
            variant_labels=request.variant_labels,
            model_capability=_template_model_capability(),
        )
    except (TemplatePlanError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    planned_labels = {run.variant_label for run in plan.runs}
    record = SeriesRecord(
        series_id=f"series-{uuid4().hex[:12]}",  # DB 版以 create_batch 生成的 batch_id 为准
        template_id=plan.template_id,
        template_version=plan.template_version,
        case_id=case_ref,
        title=f"{plan.template_id} · {case_ref}",
        variant_labels=[variant.label for variant in template.variants if variant.label in planned_labels],
        fixed_conditions=plan.fixed_conditions,
        fixed_conditions_hash=plan.fixed_conditions_hash,
        advanced=request.advanced or {},
        preset_id=request.preset_id,
        formal_min_repeat_count=template.formal_min_repeat_count,
    )
    try:
        record = _SERIES_STORE.create(record)
    except DataServiceError as exc:
        raise HTTPException(status_code=503, detail=f"数据服务不可用,实验组未创建:{exc}") from exc
    series_id = record.series_id
    return {
        "series_id": series_id,
        "template_id": record.template_id,
        "case_id": record.case_id,
        "variant_labels": record.variant_labels,
        "definition_hash": record.fixed_conditions_hash,
        "formal_min_repeat_count": record.formal_min_repeat_count,
        "runs_url": f"/api/v1/experiment-series/{series_id}/runs",
        "statistics_url": f"/api/v1/statistics/experiment-series/{series_id}",
    }


@app.post("/api/v1/experiment-series/{series_id}/runs")
def create_series_run(
    series_id: str,
    request: SeriesRunRequest,
    account: Annotated[dict[str, Any], Depends(require_login)],
) -> dict[str, Any]:
    """创建一个且仅一个 Agent 运行(方案 13.4/13.5)。

    - 幂等:同键同请求体重试返回原运行;同键不同变体返回 409;
    - 单活跃运行:同一实验组进行中的运行未完成前,新请求返回 409;
    - 失败不自动启动下一个运行;用户可再次 POST 继续积累样本。
    """
    request_hash = sha256_hex(json.dumps({"variant_id": request.variant_id}, sort_keys=True))
    try:
        entry, replayed = _SERIES_STORE.begin_run(
            series_id,
            variant_id=request.variant_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
        )
    except SeriesIdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except SeriesConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if replayed:
        return _series_run_entry_view(entry, series_id)
    if not _BATCH_SLOTS.acquire(blocking=False):
        # 回滚排队条目:下一次同键重试可以重新发起,而不是重放一次"未执行"的失败
        _SERIES_STORE.cancel_run(series_id, entry["run_key"])
        raise HTTPException(status_code=429, detail="已有评测任务在运行,请稍后再发起")
    model = os.getenv("LLM_MODEL", "Qwen/Qwen3.6-35B-A3B")

    def task() -> None:
        succeeded = False
        payload: dict[str, Any] = {}
        try:
            _SERIES_STORE.mark_running(series_id, entry["run_key"])
            payload = execute_series_run(
                _SERIES_STORE.get(series_id),
                request.variant_id,
                model=model,
                model_capability=_template_model_capability(),
                max_agent_steps=_public_service.quota.max_agent_steps,
            )
            payload["repeat_index"] = entry["repeat_index"]  # 登记序号回写,统计与展示一致
            _SERIES_STORE.complete_run(series_id, entry["run_key"], payload)
            succeeded = True
        except Exception as exc:  # noqa: BLE001 —— 失败进入可见状态,不自动启动下一个运行
            _SERIES_STORE.fail_run(series_id, entry["run_key"], f"{type(exc).__name__}: {exc}")
        finally:
            _BATCH_SLOTS.release()
        if not succeeded:
            return
        # 槽位已释放:agent_runs 落库是纯簿记,不占用 Agent 并发槽;
        # 失败不影响登记(状态文档已有正本)
        record = _SERIES_STORE.get(series_id)
        if record is None:
            return
        try:
            _persist_series_run(_data(), record, payload)
        except Exception as exc:  # noqa: BLE001
            print(f"[run_api] 实验组运行落库失败(登记保留):{type(exc).__name__}: {exc}")

    threading.Thread(target=task, daemon=True).start()
    return _series_run_entry_view(entry, series_id)


@app.get("/api/v1/experiment-series/{series_id}")
def get_experiment_series(
    series_id: str,
    account: Annotated[dict[str, Any], Depends(require_login)],
) -> dict[str, Any]:
    """实验组详情:冻结定义 + 样本积累状态(不显示强迫用户完成的百分比)。"""
    record = _SERIES_STORE.get(series_id)
    if record is None:
        raise HTTPException(status_code=404, detail="实验组不存在")
    active = record.active_run()
    return {
        "series_id": record.series_id,
        "template_id": record.template_id,
        "template_version": record.template_version,
        "case_id": record.case_id,
        "title": record.title,
        "status": record.status,
        "definition_hash": record.fixed_conditions_hash,
        "variant_labels": record.variant_labels,
        "formal_min_repeat_count": record.formal_min_repeat_count,
        "counts_by_variant": record.counts_by_variant(),
        "total_runs": sum(1 for row in record.runs if row.get("status") == "done"),
        "active_run": _series_run_entry_view(active, series_id) if active else None,
        "created_at": record.created_at,
    }


@app.get("/api/v1/experiment-series/{series_id}/runs")
def list_series_runs(
    series_id: str,
    account: Annotated[dict[str, Any], Depends(require_login)],
) -> dict[str, Any]:
    """实验组内全部独立运行(完成/进行中/失败,含各自证据)。"""
    record = _SERIES_STORE.get(series_id)
    if record is None:
        raise HTTPException(status_code=404, detail="实验组不存在")
    return {
        "series_id": series_id,
        "runs": [_series_run_entry_view(row, series_id) for row in record.runs],
    }


@app.get("/api/v1/statistics/experiment-series/{series_id}")
def get_series_statistics(
    series_id: str,
    account: Annotated[dict[str, Any], Depends(require_login)],
) -> dict[str, Any]:
    """实验组累计统计快照(P0-7):纯代码从已完成 Run 全量重算,不产生任何 LLM 请求。

    失败运行以无效证据身份进入 excluded_runs,保持排除口径透明。
    """
    record = _SERIES_STORE.get(series_id)
    if record is None:
        raise HTTPException(status_code=404, detail="实验组不存在")
    runs: list[dict[str, Any]] = []
    for row in record.runs:
        if row.get("status") == "done" and isinstance(row.get("payload"), dict):
            runs.append(row["payload"])
        elif row.get("status") == "failed":
            runs.append(
                {
                    "run_id": row.get("run_key"),
                    "variant_label": row.get("variant_id"),
                    "repeat_index": row.get("repeat_index"),
                    "config_hash": "",
                    "validity": "INVALID",
                    "stop_reason": "RUN_FAILED",
                    "actual_agent_steps": 0,
                    "duration_ms": 0,
                    "tool_calls": [],
                    "error": row.get("error"),
                }
            )
    report = {
        "template_id": record.template_id,
        "template_version": record.template_version,
        "fixed_conditions_hash": record.fixed_conditions_hash,
        "runs": runs,
    }
    from bdlh_runtime.statistics import build_snapshot

    return build_snapshot(series_id, report=report, planned_variants=record.variant_labels)


@app.post("/api/v1/public/test-jobs")
def create_public_test_job(payload: dict[str, Any], request: Request, response: Response) -> dict[str, Any]:
    """创建匿名测试任务:校验配置并立即返回 job_id;执行在后台进行。

    请求只允许固定编号与配置字段;message/prompt/system_prompt/tool_schema/
    mock_result/model_base_url/api_key 等字段一律拒绝。
    """
    token = _anon_token(request, response)
    try:
        job = _public_service.create_job(payload, anonymous_id_hash=sha256_hex(token))
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
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
        progress.pop("phase", None)


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


def _save_batch_report_best_effort(data: DataClient, batch_id: str, payload: dict[str, Any]) -> None:
    """执行报告落库(尽力而为):列未迁移或 data 不可达时只记日志,不影响批次完成;

    磁盘工件(_persist_artifact)始终保留,作为报告读取的兜底来源。
    """
    try:
        data.save_batch_report(batch_id, payload)
    except Exception as exc:  # noqa: BLE001 —— 报告持久化失败不阻断批次终态
        print(f"[run_api] 批次报告落库失败(已保留本地工件):{type(exc).__name__}: {exc}")


def _persist_artifact(batch_id: str, payload: dict[str, Any]) -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    (ARTIFACTS_DIR / f"{batch_id}.json").write_text(content, encoding="utf-8")
    (ARTIFACTS_DIR / "latest.json").write_text(content, encoding="utf-8")
