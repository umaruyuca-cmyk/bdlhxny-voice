"""匿名测试公共服务:任务创建、限额校验、后台执行与取消。

- 后台执行:创建接口只校验并落盘任务,执行在后台线程进行,页面关闭不停止;
- 进度持久化:每个单元完成后立即写盘(JobStore),服务重启可恢复;
- 取消:只阻止尚未开始的单元,已产生的运行与费用保留;不自动补跑;
- 匿名任务固定 publishable=false,不自动进入正式指标和公告。

执行器可注入(测试用 Fake);生产默认调用 experiments.compression /
experiments.comparison 的真实实现(LLM 配置唯一真源是服务端 env)。
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
    COMPRESSION_SCOPE_FULL_MATRIX,
    COMPRESSION_SCOPES,
    RunUnit,
    TestType,
    plan_comparison_runs,
    plan_compression_matrix,
    validate_repeat_count,
)
from bdlh_runtime.experiments.comparison import (
    CaseRepository,
    ComparisonCaseError,
    resolve_visible_tools,
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
        comparison_executor: Callable[..., Any] | None = None,
        compression_executor: Callable[..., Any] | None = None,
        thread_factory: Callable[..., threading.Thread] | None = None,
    ):
        self.store = store
        self.case_repository = case_repository
        self.quota = quota or PublicQuotaConfig.from_env()
        # 生产执行器:async (job, ...) -> dict;测试注入同步/假实现均可
        self._comparison_executor = comparison_executor or _default_comparison_executor
        self._compression_executor = compression_executor or _default_compression_executor
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

        if test_type is TestType.COMPARISON_CASE:
            job = self._create_comparison_job(request, job_id=new_job_id())
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

    def _create_comparison_job(self, request: dict[str, Any], *, job_id: str) -> JobRecord:
        case_id = str(request.get("case_id") or "")
        if not case_id:
            raise PublicTestError("对比用例必须提供 case_id")
        if self.case_repository is None:
            raise PublicTestError("当前服务未配置用例库,不能发起对比用例测试")
        case = self.case_repository.get_public_case(case_id)
        if case is None:
            raise PublicTestError(f"未知或非公开对比用例:{case_id}")
        repeat_count = request.get("repeat_count")
        try:
            validate_repeat_count(TestType.COMPARISON_CASE, int(repeat_count))
        except (TypeError, ValueError):
            raise PublicTestError(
                f"对比用例 repeat_count 只能是 {list(self.quota.repeat_options)},收到 {repeat_count!r}"
            ) from None
        selected_raw = request.get("selected_tool_ids")
        try:
            selected, custom = resolve_visible_tools(case, selected_raw)
        except ComparisonCaseError as exc:
            raise PublicTestError(str(exc)) from None
        units = plan_comparison_runs(case.case_id, int(repeat_count))
        return JobRecord(
            job_id=job_id,
            test_type=TestType.COMPARISON_CASE.value,
            execution_scope="comparison-full",
            status=JOB_STATUS_QUEUED,
            case_id=case.case_id,
            case_version=case.case_version,
            repeat_count=int(repeat_count),
            selected_tool_ids=list(selected),
            custom_conditions=custom,
            fixture_set_id=case.fixture_set_id,
            units=[
                JobUnit(seq=index + 1, unit_id=unit.unit_id, agent_mode_id=unit.agent_mode_id,
                        repeat_index=unit.repeat_index)
                for index, unit in enumerate(units)
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
            units = [
                JobUnit(seq=1, unit_id=f"{session_id}:{context_variant}:{agent_mode_id}",
                        agent_mode_id=str(agent_mode_id), repeat_index=0,
                        context_variant=str(context_variant))
            ]
        elif scope == COMPRESSION_SCOPE_FULL_MATRIX:
            matrix: list[RunUnit] = plan_compression_matrix(session_id)
            units = [
                JobUnit(seq=index + 1, unit_id=unit.unit_id, agent_mode_id=unit.agent_mode_id,
                        repeat_index=0, context_variant=unit.context_variant)
                for index, unit in enumerate(matrix)
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
            matrix_used = sum(
                1 for row in todays
                if row.test_type == TestType.COMPRESSION_CASE.value
                and row.execution_scope == COMPRESSION_SCOPE_FULL_MATRIX
            )
            context_used = sum(
                1 for row in todays
                if row.test_type == TestType.COMPRESSION_CASE.value
                and row.execution_scope != COMPRESSION_SCOPE_FULL_MATRIX
            )
            matrix_exhausted = (
                job.execution_scope == COMPRESSION_SCOPE_FULL_MATRIX
                and matrix_used >= self.quota.compression_matrix_daily_jobs
            )
            if matrix_exhausted:
                raise PublicTestError(
                    f"今日完整 4×3 测试次数已达上限({self.quota.compression_matrix_daily_jobs})"
                )
            context_exhausted = (
                job.execution_scope != COMPRESSION_SCOPE_FULL_MATRIX
                and context_used >= self.quota.compression_context_daily_jobs
            )
            if context_exhausted:
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
            if job.execution_scope == COMPRESSION_SCOPE_FULL_MATRIX
            else self.quota.max_job_duration_s
        )
        try:
            if job.test_type == TestType.COMPARISON_CASE.value:
                result = self._comparison_executor(job)
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
                       "skipped_unit_ids", "stats", "fingerprint"}
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
    }
)


def _default_comparison_executor(job: JobRecord) -> dict[str, Any]:
    """生产执行器(同步包装):从仓库读取用例,按冻结条件运行 3×repeat_count 次。"""
    import asyncio
    from dataclasses import asdict

    from bdlh_runtime.experiments import default_max_agent_steps
    from bdlh_runtime.experiments.comparison import run_comparison_case

    assert job.case_id
    from bdlh_runtime.experiments.public_case_repository import get_case_repository

    repository = get_case_repository()
    case = repository.get_public_case(job.case_id)
    if case is None:
        raise PublicTestError(f"未知或非公开对比用例:{job.case_id}")
    result = asyncio.run(
        run_comparison_case(
            case,
            job.repeat_count,
            selected_tool_ids=tuple(job.selected_tool_ids) or None,
            max_agent_steps=job.max_agent_steps or default_max_agent_steps(),
            should_stop=lambda: job.cancel_requested,
        )
    )
    payload = asdict(result)
    payload["runs"] = [row.__dict__ for row in result.runs]
    return payload


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
                job.agent_mode_id or "",
                max_agent_steps=steps,
            )
        )
        return {"cells": [cell.__dict__], "session_id": job.session_id,
                "frozen_artifact_hashes": {cell.context_variant: cell.context_artifact_hash}}
    return asyncio.run(
        compression_module.run_full_matrix(
            job.session_id,
            max_agent_steps=steps,
            should_stop=should_stop,
        )
    )
