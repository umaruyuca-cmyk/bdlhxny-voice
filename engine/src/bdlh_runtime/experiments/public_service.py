"""匿名测试公共服务:任务创建、限额校验、后台执行与取消。

- 后台执行:创建接口只校验并落盘任务,执行在后台线程进行,页面关闭不停止;
- 进度持久化:每个单元完成后立即写盘(JobStore),服务重启可恢复;
- 取消:只阻止尚未开始的单元,已产生的运行与费用保留;不自动补跑;
- 匿名任务固定 publishable=false,不自动进入正式指标和公告。

执行器可注入(测试用 Fake);生产默认调用 experiments.compression /
experiments.template_runner 的真实实现(LLM 配置唯一真源是服务端 env)。
对比用例一律经实验模板发起(template_id)。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from bdlh_runtime.experiments import (
    COMPRESSION_SCOPE_CONTEXT_ONLY,
    COMPRESSION_SCOPE_CURRENT_COMBO,
    COMPRESSION_SCOPE_NATIVE_MATRIX,
    COMPRESSION_SCOPES,
    NATIVE_AGENT_MODE_ID,
    RunUnit,
    TestType,
    plan_native_context_runs,
    validate_repeat_count,
)
from bdlh_runtime.experiments.comparison import (
    CaseRepository,
)
from bdlh_runtime.experiments.job_store import (
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETE,
    JOB_STATUS_FAILED,
    JOB_STATUS_PARTIAL,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    REQUESTER_ANONYMOUS,
    RUN_PURPOSE_PUBLIC_TRIAL,
    UNIT_STATUS_CANCELLED,
    UNIT_STATUS_COMPLETE,
    UNIT_STATUS_QUEUED,
    JobRecord,
    JobStore,
    JobUnit,
    new_job_id,
)
from bdlh_runtime.experiments.quota import PublicQuotaConfig


class PublicTestError(ValueError):
    """请求不合法或超出限额;message 面向页面展示,不含内部细节。"""


class AnonymousJobService:
    def __init__(
        self,
        store: JobStore,
        *,
        case_repository: CaseRepository | None = None,
        quota: PublicQuotaConfig | None = None,
        compression_executor: Callable[..., Any] | None = None,
        template_executor: Callable[..., Any] | None = None,
        thread_factory: Callable[..., threading.Thread] | None = None,
    ):
        self.store = store
        self.case_repository = case_repository
        self.quota = quota or PublicQuotaConfig.from_env()
        # 生产执行器:async (job, ...) -> dict;测试注入同步/假实现均可
        self._compression_executor = compression_executor or _default_compression_executor
        # 模板化匿名任务执行器(模板不只可看,也能发起)
        self._template_executor = template_executor or _default_template_executor
        self._thread_factory = thread_factory or (
            lambda target: threading.Thread(target=target, daemon=True)
        )
        self._running_lock = threading.Lock()

    # ------------------------------------------------------------------ 创建

    def create_job(self, request: dict[str, Any], *, anonymous_id_hash: str) -> JobRecord:
        """校验匿名测试请求并创建后台任务;立即返回,不等待执行完成。"""
        unknown_fields = set(request) - _ALLOWED_REQUEST_FIELDS
        if unknown_fields:
            raise PublicTestError(
                f"请求包含不允许的字段:{sorted(unknown_fields)};匿名测试不接受问题正文、"
                "系统提示、工具定义、Mock 返回、模型地址或密钥"
            )
        test_type_raw = str(request.get("test_type") or "")
        try:
            test_type = TestType(test_type_raw)
        except ValueError:
            raise PublicTestError(
                f"test_type 只能是 COMPRESSION_CASE 或 COMPARISON_CASE,收到 {test_type_raw!r}"
            ) from None

        if "template_id" in request:
            job = self._create_template_job(request, job_id=new_job_id())
        elif test_type is TestType.COMPARISON_CASE:
            raise PublicTestError(
                "对比用例必须经实验模板发起:请在请求中提供 template_id"
                "(请在请求中提供 template_id)"
            )
        else:
            job = self._create_compression_job(request, job_id=new_job_id())

        job.requester_type = REQUESTER_ANONYMOUS
        job.anonymous_id_hash = anonymous_id_hash
        job.run_purpose = RUN_PURPOSE_PUBLIC_TRIAL
        job.publishable = False  # 匿名运行固定不可发布
        job.max_agent_steps = self.quota.max_agent_steps
        job.quota_snapshot = self.quota.as_dict()

        self._check_quota(job)
        self.store.save(job)

        def target() -> None:
            self.execute(job.job_id)

        thread = self._thread_factory(target)
        if thread is not None:
            thread.start()
        return job

    def _create_template_job(self, request: dict[str, Any], *, job_id: str) -> JobRecord:
        """模板化匿名任务:正式单变量模板 → 精确运行单元(混合路线阻断1)。

        - 只允许「允许匿名」且支持 COMPARISON_CASE 的模板;
        - 计划全部在创建时经 plan_template_batch 校验(权限/区间/上限/预设);
        - 单元 = 计划内的每次运行(unit_id 即模板 run_id),执行走统一原生底座。
        """
        from bdlh_runtime.experiments.templates import (
            ROLE_ANONYMOUS,
            TemplatePlanError,
            plan_template_batch,
        )

        template_id = str(request.get("template_id") or "")
        case_id = str(request.get("case_id") or "")
        if not case_id:
            raise PublicTestError("模板任务必须提供 case_id(模板作用于固定用例)")
        if self.case_repository is None:
            raise PublicTestError("当前服务未配置用例库,不能发起模板测试")
        case = self.case_repository.get_public_case(case_id)
        if case is None:
            raise PublicTestError(f"未知或非公开对比用例:{case_id}")
        repeat_raw = request.get("repeat_count", 1)
        try:
            repeat_count = int(repeat_raw)
        except (TypeError, ValueError):
            raise PublicTestError(f"repeat_count 必须是整数,收到 {repeat_raw!r}") from None
        preset_id = request.get("preset_id")
        try:
            plan = plan_template_batch(
                template_id,
                repeat_count=repeat_count,
                role=ROLE_ANONYMOUS,
                preset_id=str(preset_id) if preset_id else None,
            )
        except TemplatePlanError as exc:
            raise PublicTestError(str(exc)) from None
        if plan.context_only or not plan.runs:
            raise PublicTestError("该模板不产生 Agent 运行(仅上下文生成),请使用压缩用例入口")
        return JobRecord(
            job_id=job_id,
            test_type=TestType.COMPARISON_CASE.value,
            execution_scope="template-batch",
            status=JOB_STATUS_QUEUED,
            case_id=case.case_id,
            case_version=case.case_version,
            repeat_count=repeat_count,
            fixture_set_id=case.fixture_set_id,
            template_id=plan.template_id,
            template_version=plan.template_version,
            template_plan_hash=plan.fixed_conditions_hash,
            template_preset_id=str(preset_id) if preset_id else None,
            units=[
                JobUnit(
                    seq=index + 1,
                    unit_id=run.run_id,
                    agent_mode_id=NATIVE_AGENT_MODE_ID,
                    repeat_index=run.repeat_index,
                    context_variant=run.variant_label,
                )
                for index, run in enumerate(plan.runs)
            ],
        )

    def _create_compression_job(self, request: dict[str, Any], *, job_id: str) -> JobRecord:
        from bdlh_runtime.experiments.compression import COMPRESSION_SESSIONS

        session_id = str(request.get("session_id") or "")
        if session_id not in {row[0] for row in COMPRESSION_SESSIONS}:
            raise PublicTestError(
                f"未知压缩 Session:{session_id!r};可用:{[row[0] for row in COMPRESSION_SESSIONS]}"
            )
        scope = str(request.get("execution_scope") or COMPRESSION_SCOPE_CONTEXT_ONLY)
        if scope not in COMPRESSION_SCOPES:
            raise PublicTestError(f"压缩用例 execution_scope 只能是 {list(COMPRESSION_SCOPES)}")
        repeat_count = request.get("repeat_count", 1)
        try:
            validate_repeat_count(TestType.COMPRESSION_CASE, int(repeat_count))
        except (TypeError, ValueError):
            raise PublicTestError("压缩用例每个实验条件固定运行 1 次,不接受其他重复次数") from None

        context_variant = request.get("context_variant")
        agent_mode_id = request.get("agent_mode_id")
        units: list[JobUnit] = []
        if scope == COMPRESSION_SCOPE_CURRENT_COMBO:
            if not context_variant or not agent_mode_id:
                raise PublicTestError("运行当前组合必须提供 context_variant 与 agent_mode_id")
            if agent_mode_id != NATIVE_AGENT_MODE_ID:
                raise PublicTestError(
                    f"运行当前组合的 agent_mode_id 只能是 {NATIVE_AGENT_MODE_ID},收到 {agent_mode_id!r}"
                )
            units = [
                JobUnit(seq=1, unit_id=f"{session_id}:{context_variant}:{agent_mode_id}",
                        agent_mode_id=str(agent_mode_id), repeat_index=0,
                        context_variant=str(context_variant))
            ]
        elif scope == COMPRESSION_SCOPE_NATIVE_MATRIX:
            # 新默认上下文运行计划:4 种上下文 × 1 种固定原生配置(4×1)
            native_units: list[RunUnit] = plan_native_context_runs(session_id)
            units = [
                JobUnit(seq=index + 1, unit_id=unit.unit_id, agent_mode_id=unit.agent_mode_id,
                        repeat_index=0, context_variant=unit.context_variant)
                for index, unit in enumerate(native_units)
            ]
        return JobRecord(
            job_id=job_id,
            test_type=TestType.COMPRESSION_CASE.value,
            execution_scope=scope,
            status=JOB_STATUS_QUEUED,
            session_id=session_id,
            context_variant=str(context_variant) if context_variant else None,
            agent_mode_id=str(agent_mode_id) if agent_mode_id else None,
            repeat_count=1,
            units=units,
        )

    # ------------------------------------------------------------------ 限额

    def _check_quota(self, job: JobRecord) -> None:
        assert job.anonymous_id_hash
        jobs = self.store.list_for_anonymous(job.anonymous_id_hash, limit=100)
        today = datetime.now(UTC).date().isoformat()
        todays = [row for row in jobs if row.created_at.startswith(today)]
        active = [row for row in todays if row.status in {JOB_STATUS_QUEUED, JOB_STATUS_RUNNING}]
        if len(active) >= self.quota.max_concurrent_jobs_per_anonymous:
            raise PublicTestError("已有测试任务在运行,请等待完成或取消后再发起新任务")
        if job.test_type == TestType.COMPARISON_CASE.value:
            used = sum(1 for row in todays if row.test_type == TestType.COMPARISON_CASE.value)
            if used >= self.quota.comparison_daily_jobs:
                raise PublicTestError(
                    f"今日对比用例测试次数已达上限({self.quota.comparison_daily_jobs}),请明天再试"
                )
        else:
            context_used = sum(
                1 for row in todays
                if row.test_type == TestType.COMPRESSION_CASE.value
            )
            if context_used >= self.quota.compression_context_daily_jobs:
                raise PublicTestError(
                    f"今日压缩上下文生成次数已达上限({self.quota.compression_context_daily_jobs})"
                )

    # ------------------------------------------------------------------ 执行

    def execute(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is None:
            return
        job.status = JOB_STATUS_RUNNING
        job.started_at = _now_iso()
        self.store.save(job)
        deadline = time.monotonic() + (
            self.quota.matrix_max_job_duration_s
            if job.execution_scope == COMPRESSION_SCOPE_NATIVE_MATRIX
            else self.quota.max_job_duration_s
        )
        try:
            if job.template_id:
                result = self._template_executor(
                    job,
                    should_stop=lambda: job.cancel_requested or time.monotonic() > deadline,
                )
            else:
                result = self._compression_executor(
                    job,
                    should_stop=lambda: job.cancel_requested or time.monotonic() > deadline,
                )
        except Exception as exc:  # noqa: BLE001 —— 任务失败进入可见状态
            job.status = JOB_STATUS_FAILED
            job.error = f"{type(exc).__name__}: {exc}"
            job.completed_at = _now_iso()
            self.store.save(job)
            return
        self._apply_result(job, result)
        cancelled = job.cancel_requested
        for unit in job.units:
            if unit.status == UNIT_STATUS_QUEUED:  # 取消只阻止尚未开始的单元
                unit.status = UNIT_STATUS_CANCELLED
        done = job.completed_unit_count()
        if cancelled and done < len(job.units):
            job.status = JOB_STATUS_CANCELLED if done == 0 else JOB_STATUS_PARTIAL
        else:
            job.status = JOB_STATUS_COMPLETE
        job.completed_at = _now_iso()
        self.store.save(job)

    def _apply_result(self, job: JobRecord, result: dict[str, Any]) -> None:
        unit_rows = {row.get("unit_id"): row for row in result.get("cells") or result.get("runs") or []}
        for unit in job.units:
            row = unit_rows.get(unit.unit_id)
            if row is None:
                if job.cancel_requested:
                    unit.status = UNIT_STATUS_CANCELLED
                continue
            unit.status = UNIT_STATUS_COMPLETE
            unit.run_id = row.get("run_id") or unit.run_id
            unit.actual_agent_steps = int(row.get("actual_agent_steps") or row.get("actual_steps") or 0)
            unit.stop_reason = str(row.get("stop_reason") or "")
            unit.duration_ms = int(row.get("duration_ms") or 0)
            unit.task_success = bool(row.get("task_success"))
            unit.validity = str(row.get("validity") or "")
        # 结果只保留公开摘要;上下文工件路径与哈希、逐单元指标
        job.result = {
            key: value
            for key, value in result.items()
            if key in {"test_type", "case_id", "case_version", "session_id", "session_version",
                       "repeat_count", "max_agent_steps", "total_runs", "unit_count",
                       "by_agent", "invalid_runs", "custom_conditions", "selected_tool_ids",
                       "fixture_set_id", "execution_order", "frozen_artifact_hashes",
                       "skipped_unit_ids", "stats", "fingerprint",
                       # 运行配置快照(阶段A3):配置体不含 gold,可进公开摘要
                       "run_configs", "fixed_conditions", "fixed_conditions_hash",
                       # 模板批次摘要(混合路线):模板标识/分类/自变量/按变体聚合
                       "template_id", "template_version", "classification",
                       "independent_variable", "by_variant", "run_count",
                       "skipped_run_ids"}
        }
        self.store.save(job)

    # ------------------------------------------------------------------ 查询/取消

    def get_job_for(self, job_id: str, anonymous_id_hash: str) -> JobRecord:
        """匿名用户只能查看自己的任务;他人的任务按不存在处理(不可枚举)。"""
        job = self.store.get(job_id)
        if job is None or job.anonymous_id_hash != anonymous_id_hash:
            raise PublicTestError("任务不存在或不属于当前匿名身份")
        return job

    def cancel_job(self, job_id: str, anonymous_id_hash: str) -> JobRecord:
        """协作取消:置停止标志,执行循环在发起新单元前检查。幂等。"""
        job = self.get_job_for(job_id, anonymous_id_hash)
        if job.status in {JOB_STATUS_QUEUED, JOB_STATUS_RUNNING}:
            job.cancel_requested = True
            if job.status == JOB_STATUS_QUEUED:
                # 尚未开始:全部单元直接取消
                for unit in job.units:
                    unit.status = UNIT_STATUS_CANCELLED
                job.status = JOB_STATUS_CANCELLED
                job.completed_at = _now_iso()
            self.store.save(job)
        return job


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


_ALLOWED_REQUEST_FIELDS = frozenset(
    {
        "test_type",
        "case_id",
        "case_version",
        "session_id",
        "session_version",
        "execution_scope",
        "context_variant",
        "agent_mode_id",
        "repeat_count",
        "selected_tool_ids",
        "idempotency_key",
        # 模板化匿名任务(混合路线):只接受模板编号与预设编号,
        # 变体数组/高级设置仍不可提交(由模板常量决定)
        "template_id",
        "preset_id",
    }
)


def _default_template_executor(
    job: JobRecord, *, should_stop: Callable[[], bool] = lambda: False
) -> dict[str, Any]:
    """生产模板执行器(同步包装):重建计划并在统一原生底座上运行。

    LLM 配置唯一真源是服务端 env(与旧入口一致);测试注入 template_executor
    替身,不触发本函数。计划重建参数与创建时一致(模板常量 + 持久化的
    repeat_count/preset_id),确定性可复现。
    """
    import asyncio

    from bdlh_runtime.experiments.public_case_repository import get_case_repository
    from bdlh_runtime.experiments.template_runner import run_template_batch
    from bdlh_runtime.experiments.templates import ROLE_ANONYMOUS, plan_template_batch

    assert job.case_id and job.template_id
    repository = get_case_repository()
    case = repository.get_public_case(job.case_id)
    if case is None:
        raise PublicTestError(f"未知或非公开对比用例:{job.case_id}")
    plan = plan_template_batch(
        job.template_id,
        repeat_count=job.repeat_count,
        role=ROLE_ANONYMOUS,
        preset_id=job.template_preset_id,
    )
    result = asyncio.run(
        run_template_batch(
            plan,
            message=case.message,
            visible_tools=case.allowed_tools,
            # llm=None:每次运行按各自生效参数构建独立客户端(温度等逐运行生效)
            llm=None,
            fixtures=list((case.conditions or {}).get("mock_fixtures") or []),
            fixture_version=str(case.fixture_set_id),
            should_stop=should_stop,
        )
    )
    # 单元对齐:_apply_result 按 unit_id 匹配,模板 run_id 即单元号
    result["runs"] = [dict(row, unit_id=row.get("run_id")) for row in result.get("runs") or []]
    return result


def _default_compression_executor(job: JobRecord, *, should_stop: Callable[[], bool] = lambda: False) -> dict[str, Any]:
    """生产执行器(同步包装):压缩用例三个操作各自映射到 compression 模块。"""
    import asyncio

    from bdlh_runtime.experiments import compression as compression_module
    from bdlh_runtime.experiments import default_max_agent_steps

    assert job.session_id
    steps = job.max_agent_steps or default_max_agent_steps()
    if job.execution_scope == COMPRESSION_SCOPE_CONTEXT_ONLY:
        result = compression_module.generate_contexts(job.session_id)
        return {
            "test_type": job.test_type,
            "session_id": result.session_id,
            "session_version": result.session_version,
            "fingerprint": result.fingerprint,
            "stats": result.stats,
            "cells": [],  # 上下文生成阶段:0 个 Agent 运行
        }
    if job.execution_scope == COMPRESSION_SCOPE_CURRENT_COMBO:
        cell = asyncio.run(
            compression_module.run_current_combo(
                job.session_id,
                job.context_variant or "",
                NATIVE_AGENT_MODE_ID,
                max_agent_steps=steps,
            )
        )
        return {"cells": [cell.__dict__], "session_id": job.session_id,
                "frozen_artifact_hashes": {cell.context_variant: cell.context_artifact_hash}}
    if job.execution_scope == COMPRESSION_SCOPE_NATIVE_MATRIX:
        return asyncio.run(
            compression_module.run_native_context_matrix(
                job.session_id,
                max_agent_steps=steps,
                should_stop=should_stop,
            )
        )
    raise PublicTestError(f"未知压缩操作 execution_scope:{job.execution_scope!r}")
