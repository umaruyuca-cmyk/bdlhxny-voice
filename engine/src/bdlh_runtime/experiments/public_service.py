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

import inspect
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
    UNIT_STATUS_FAILED,
    UNIT_STATUS_INVALID,
    UNIT_STATUS_QUEUED,
    UNIT_STATUS_RUNNING,
    JobRecord,
    JobStore,
    JobUnit,
    new_job_id,
)
from bdlh_runtime.experiments.quota import PublicQuotaConfig


class PublicTestError(ValueError):
    """请求不合法或超出限额;message 面向页面展示,不含内部细节。"""


class IdempotencyConflict(PublicTestError):
    """同一幂等键配不同请求体:拒绝(409),不静默复用旧任务。"""

    def __init__(self) -> None:
        super().__init__("幂等键冲突:该键已被不同参数的请求使用,请刷新页面后重新提交")


class _PublicProgressEventSink:
    """把 RunRecorder 的真实事件同步投影为匿名任务进度。"""

    def __init__(self, on_event: Callable[[dict[str, Any]], None]) -> None:
        self._on_event = on_event

    def attach(self, recorder: Any) -> None:
        # run.started 在 recorder 构造时已经产生，先补投，再订阅后续事件。
        for event in list(recorder.record.events):
            self._on_event(dict(event))
        recorder.add_event_listener(self._on_event)


def _request_hash(request: dict[str, Any]) -> str:
    """请求体规范化哈希(键排序;不含幂等键本身),判定"同一请求"的依据。"""
    import hashlib
    import json as _json

    payload = {key: request[key] for key in sorted(request) if key != "idempotency_key"}
    digest = hashlib.sha256(_json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return f"sha256:{digest.hexdigest()}"


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
        self._thread_factory = thread_factory or (lambda target: threading.Thread(target=target, daemon=True))
        self._running_lock = threading.Lock()

    # ------------------------------------------------------------------ 创建

    def create_job(self, request: dict[str, Any], *, anonymous_id_hash: str) -> JobRecord:
        """校验匿名测试请求并创建后台任务;立即返回,不等待执行完成。

        幂等(P0-4):请求可携带 ``idempotency_key``;同一匿名身份 + 同一键 +
        同一请求体哈希的重复提交(网络重试/并发)返回原任务,不创建第二个任务、
        不产生额外模型费用;同键不同请求体返回 409(IdempotencyConflict)。
        查重 → 限额 → 保存 在 ``_running_lock`` 临界区内原子执行。
        """
        unknown_fields = set(request) - _ALLOWED_REQUEST_FIELDS
        if unknown_fields:
            raise PublicTestError(
                f"请求包含不允许的字段:{sorted(unknown_fields)};匿名测试不接受问题正文、"
                "系统提示、工具定义、Mock 返回、模型地址或密钥"
            )
        idempotency_key = str(request.get("idempotency_key") or "").strip() or None
        if idempotency_key is not None and (len(idempotency_key) < 8 or len(idempotency_key) > 128):
            raise PublicTestError("idempotency_key 长度必须在 8–128 字符之间")

        with self._running_lock:
            if idempotency_key is not None:
                existing = self.store.find_by_idempotency_key(idempotency_key, anonymous_id_hash=anonymous_id_hash)
                if existing is not None:
                    if existing.request_hash and existing.request_hash != _request_hash(request):
                        raise IdempotencyConflict() from None
                    return existing  # 同一请求的重试/并发提交:返回原任务

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
                    "对比用例必须经实验模板发起:请在请求中提供 template_id(请在请求中提供 template_id)"
                )
            else:
                job = self._create_compression_job(request, job_id=new_job_id())

            job.requester_type = REQUESTER_ANONYMOUS
            job.anonymous_id_hash = anonymous_id_hash
            job.run_purpose = RUN_PURPOSE_PUBLIC_TRIAL
            job.publishable = False  # 匿名运行固定不可发布
            job.max_agent_steps = self.quota.max_agent_steps
            job.quota_snapshot = self.quota.as_dict()
            job.idempotency_key = idempotency_key
            job.request_hash = _request_hash(request) if idempotency_key else None

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

        - 上下文模板(COMPRESSION_CASE):委托压缩用例创建链(session/scope 校验、
          context-only 零单元或原生 4×1),任务记录保留模板口径;
        - 对比模板(COMPARISON_CASE):只允许「允许匿名」的模板,计划全部在创建时
          经 plan_template_batch 校验(权限/区间/上限/预设),单元 = 计划内的
          每次运行(unit_id 即模板 run_id),执行走统一原生底座;一次只运行一个
          Agent——匿名可用 variant_label 选单个变体发起 1 次运行,其余多运行
          展开一律拒绝(不保留隐式批量执行)。
        """
        from bdlh_runtime.experiments.templates import (
            ROLE_ANONYMOUS,
            TemplatePlanError,
            get_template,
            plan_template_batch,
        )

        template_id = str(request.get("template_id") or "")
        try:
            template = get_template(template_id)
        except TemplatePlanError as exc:
            raise PublicTestError(str(exc)) from None
        if not template.anonymous_allowed:
            raise PublicTestError("该模板不对匿名用户开放;请登录后从运行台发起")
        if "COMPRESSION_CASE" in template.allowed_test_types:
            # 长上下文模板(匿名可用):session/scope 语义,走压缩用例链(执行器同为压缩执行器)。
            # 压缩方法对照(compression-method-comparison)为 owner-only,不经匿名服务。
            compression_request = {key: value for key, value in request.items() if key != "template_id"}
            job = self._create_compression_job(compression_request, job_id=job_id)
            job.template_id = template.template_id
            job.template_version = template.version
            return job
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
        # 匿名单变体口径:variant_label 在模板既有变体中做子集选择,发起恰好 1 次
        # 运行;变体定义仍由模板冻结,不接受任意变体定义或变体数组
        variant_label = str(request.get("variant_label") or "").strip() or None
        if variant_label and repeat_count != 1:
            raise PublicTestError("匿名单变体运行固定 1 次(repeat_count=1);多次重复请登录后从实验组流程逐样本追加")
        try:
            plan = plan_template_batch(
                template_id,
                repeat_count=repeat_count,
                role=ROLE_ANONYMOUS,
                preset_id=str(preset_id) if preset_id else None,
                variant_labels=[variant_label] if variant_label else None,
            )
        except TemplatePlanError as exc:
            raise PublicTestError(str(exc)) from None
        if plan.context_only or not plan.runs:
            raise PublicTestError("该模板不产生 Agent 运行(仅上下文生成),请使用压缩用例入口")
        # 一次只运行一个 Agent(P0-1):匿名模板任务不再把计划内的全部变体 ×
        # 重复展开为多个单元;多运行入口明确关闭,不保留隐式批量执行。
        if len(plan.runs) > 1:
            raise PublicTestError(
                f"该模板一次会展开 {len(plan.runs)} 个 Agent 运行;匿名模板多运行入口已关闭,"
                "可用 variant_label 选择单个变体发起 1 次运行,"
                "或登录后从实验组流程逐样本发起(每次点击只创建一个运行)"
            )
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
            raise PublicTestError(f"未知压缩 Session:{session_id!r};可用:{[row[0] for row in COMPRESSION_SESSIONS]}")
        scope = str(request.get("execution_scope") or COMPRESSION_SCOPE_CONTEXT_ONLY)
        if scope not in COMPRESSION_SCOPES:
            raise PublicTestError(f"压缩用例 execution_scope 只能是 {list(COMPRESSION_SCOPES)}")
        # 一次只运行一个 Agent(P0-1 修复):原生 4×1 一次创建 4 个运行,入口明确关闭
        if scope == COMPRESSION_SCOPE_NATIVE_MATRIX:
            raise PublicTestError(
                "原生 4×1 一次创建多个 Agent 运行,该入口已关闭;请逐个发起「运行当前组合」(一次一个运行)"
            )
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
                JobUnit(
                    seq=1,
                    unit_id=f"{session_id}:{context_variant}:{agent_mode_id}",
                    agent_mode_id=str(agent_mode_id),
                    repeat_index=0,
                    context_variant=str(context_variant),
                )
            ]
        elif scope == COMPRESSION_SCOPE_NATIVE_MATRIX:
            # 新默认上下文运行计划:4 种上下文 × 1 种固定原生配置(4×1)
            native_units: list[RunUnit] = plan_native_context_runs(session_id)
            units = [
                JobUnit(
                    seq=index + 1,
                    unit_id=unit.unit_id,
                    agent_mode_id=unit.agent_mode_id,
                    repeat_index=0,
                    context_variant=unit.context_variant,
                )
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
                raise PublicTestError(f"今日对比用例测试次数已达上限({self.quota.comparison_daily_jobs}),请明天再试")
        else:
            context_used = sum(1 for row in todays if row.test_type == TestType.COMPRESSION_CASE.value)
            if context_used >= self.quota.compression_context_daily_jobs:
                raise PublicTestError(f"今日压缩上下文生成次数已达上限({self.quota.compression_context_daily_jobs})")

    # ------------------------------------------------------------------ 执行

    def _record_progress(
        self,
        job: JobRecord,
        *,
        stage: str,
        phase: str,
        event_type: str | None = None,
        detail: str = "",
        occurred_at: str | None = None,
        persist: bool = True,
    ) -> None:
        """持久化公开安全的实时进度；只记录标签与计数，不记录运行正文。"""
        now = occurred_at or _now_iso()
        progress = dict(job.progress or {})
        events = list(progress.get("events") or [])
        previous_stage = str(progress.get("stage") or "")
        if stage in {"complete", "failed"} and previous_stage not in {"", "complete", "failed"}:
            progress["last_stage"] = previous_stage
        if event_type:
            events.append(
                {
                    "index": int(progress.get("event_count") or 0) + 1,
                    "event_type": event_type,
                    "stage": stage,
                    "label": phase,
                    "detail": detail,
                    "occurred_at": now,
                }
            )
            progress["event_count"] = int(progress.get("event_count") or 0) + 1
        if progress.get("stage") != stage or progress.get("phase") != phase:
            progress["phase_started_at"] = now
        progress.update(
            {
                "stage": stage,
                "phase": phase,
                "updated_at": now,
                "events": events[-40:],
            }
        )
        job.progress = progress
        if persist:
            latest = self.store.get(job.job_id)
            if latest is not None and latest.cancel_requested:
                job.cancel_requested = True
            self.store.save(job)

    def _runtime_progress(self, job: JobRecord, event: dict[str, Any]) -> None:
        """RunRecorder 事件 → 用户可读的当前步骤与最近事件。"""
        event_type = str(event.get("eventType") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        occurred_at = str(event.get("occurredAt") or _now_iso())
        stage, phase, detail = "agent", event_type, ""
        if event_type == "run.started":
            stage, phase = "context", "已装载固定用例，正在准备上下文与工具目录"
            variant = str(payload.get("variantId") or "")
            detail = f"受控变体: {variant}" if variant else ""
            for unit in job.units:
                if unit.status == UNIT_STATUS_QUEUED and (not variant or unit.context_variant == variant):
                    unit.status = UNIT_STATUS_RUNNING
                    job.progress["current_unit"] = unit.unit_id
                    break
        elif event_type == "context.completed":
            stage, phase = "context", "上下文已构建，正在准备首轮模型请求"
            detail = f"策略: {payload.get('strategy')}" if payload.get("strategy") else ""
        elif event_type == "model.requested":
            count = 1 + sum(
                1 for row in (job.progress.get("events") or []) if row.get("event_type") == "model.requested"
            )
            stage, phase = "agent", f"第 {count} 轮模型请求已发出，等待模型响应"
            tools = payload.get("tools") if isinstance(payload.get("tools"), list) else []
            detail = f"模型: {payload.get('model') or 'configured-model'} · 可见工具 {len(tools)} 个"
        elif event_type == "model.completed":
            sequence = payload.get("sequence") or "?"
            stage, phase = "agent", f"第 {sequence} 轮模型响应已返回"
            detail = f"决策: {payload.get('decision') or '—'} · 耗时 {payload.get('durationMs') or 0} ms"
        elif event_type == "model.result_appended":
            stage, phase = "agent", "模型结果已加入上下文，继续 Agent 循环"
        elif event_type == "tool.requested":
            tool = str(payload.get("tool") or "未知工具")
            stage, phase, detail = "agent", f"正在执行工具 {tool}", f"工具调用 #{payload.get('sequence') or '?'}"
        elif event_type == "tool.completed":
            tool = str(payload.get("tool") or "未知工具")
            stage, phase = "agent", f"工具 {tool} 已返回，继续模型推理"
            detail = f"状态: {payload.get('status') or '—'} · 耗时 {payload.get('durationMs') or 0} ms"
        elif event_type == "guardrail.completed":
            stage, phase = "agent", "工具治理检查完成"
            detail = f"决策: {payload.get('decision') or '—'}"
        elif event_type == "output.completed":
            stage, phase = "output", "最终回答已生成，正在整理运行结果"
        elif event_type == "judgment.completed":
            stage, phase = "finalizing", "结果评判已完成，正在归档"
        elif event_type == "run.completed":
            stage, phase = "finalizing", "Agent 运行已结束，正在汇总指标与归档"
            detail = f"状态: {payload.get('status') or '—'} · 总耗时 {payload.get('durationMs') or 0} ms"
        self._record_progress(
            job,
            stage=stage,
            phase=phase,
            event_type=event_type,
            detail=detail,
            occurred_at=occurred_at,
        )

    @staticmethod
    def _accepts_kwarg(executor: Callable[..., Any], name: str) -> bool:
        try:
            params = inspect.signature(executor).parameters.values()
        except (TypeError, ValueError):
            return False
        return any(param.kind == inspect.Parameter.VAR_KEYWORD or param.name == name for param in params)

    def _run_executor(
        self,
        executor: Callable[..., Any],
        job: JobRecord,
        *,
        should_stop: Callable[[], bool],
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"should_stop": should_stop}
        optional = {
            "on_phase": lambda text: self._record_progress(
                job,
                stage="context" if "上下文" in text or "摘要" in text else "preparing",
                phase=str(text),
                event_type="phase.changed",
            ),
            "on_run_done": lambda _row: self._record_progress(
                job, stage="finalizing", phase="Agent 单元已结束，正在汇总结果", event_type="unit.completed"
            ),
            "event_sink": _PublicProgressEventSink(lambda event: self._runtime_progress(job, event)),
        }
        for name, value in optional.items():
            if self._accepts_kwarg(executor, name):
                kwargs[name] = value
        return executor(job, **kwargs)

    def execute(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is None:
            return
        job.status = JOB_STATUS_RUNNING
        job.started_at = _now_iso()
        self._record_progress(
            job,
            stage="preparing",
            phase="正在校验实验配置并装载固定用例",
            event_type="job.started",
            persist=False,
        )
        self.store.save(job)
        deadline = time.monotonic() + (
            self.quota.matrix_max_job_duration_s
            if job.execution_scope == COMPRESSION_SCOPE_NATIVE_MATRIX
            else self.quota.max_job_duration_s
        )

        def should_stop() -> bool:
            latest = self.store.get(job_id)
            if latest is not None and latest.cancel_requested:
                job.cancel_requested = True
            return job.cancel_requested or time.monotonic() > deadline

        try:
            if job.template_id and job.test_type == TestType.COMPARISON_CASE.value:
                # 对比模板任务:统一原生底座执行器;上下文模板任务走压缩执行链
                result = self._run_executor(self._template_executor, job, should_stop=should_stop)
            else:
                result = self._run_executor(self._compression_executor, job, should_stop=should_stop)
        except Exception as exc:  # noqa: BLE001 —— 任务失败进入可见状态
            job.status = JOB_STATUS_FAILED
            job.error = f"{type(exc).__name__}: {exc}"
            job.completed_at = _now_iso()
            for unit in job.units:
                if unit.status == UNIT_STATUS_RUNNING:
                    unit.status = UNIT_STATUS_FAILED
                    unit.error = job.error
            self._record_progress(
                job,
                stage="failed",
                phase="执行失败",
                event_type="job.failed",
                detail=job.error,
                persist=False,
            )
            self.store.save(job)
            return
        self._apply_result(job, result)
        cancelled = job.cancel_requested
        for unit in job.units:
            if unit.status == UNIT_STATUS_QUEUED:  # 取消只阻止尚未开始的单元
                unit.status = UNIT_STATUS_CANCELLED
        done = job.completed_unit_count()
        failed_units = [unit for unit in job.units if unit.status in {UNIT_STATUS_FAILED, UNIT_STATUS_INVALID}]
        unfinished_units = [unit for unit in job.units if unit.status in {UNIT_STATUS_QUEUED, UNIT_STATUS_RUNNING}]
        budget_reason = str(result.get("budget_terminated") or "") if isinstance(result, dict) else ""
        if budget_reason:
            # 预算终止(§11.2):已完成单元与工件保留,任务进入明确终态,不冒充完整成功
            job.error = budget_reason
            job.status = JOB_STATUS_PARTIAL if done else JOB_STATUS_FAILED
        elif cancelled and done < len(job.units):
            job.status = JOB_STATUS_CANCELLED if done == 0 else JOB_STATUS_PARTIAL
        elif failed_units or unfinished_units:
            # 执行器返回并不等于运行成功。模型超时/不可用会产出一条带
            # INVALID/FAILED 证据的结果行；缺少结果行也不能冒充完整成功。
            job.status = JOB_STATUS_PARTIAL if done else JOB_STATUS_FAILED
            first_error = next((unit.error for unit in failed_units if unit.error), None)
            job.error = first_error or ("部分运行单元失败" if done else "运行单元失败或未产生结果")
        else:
            job.status = JOB_STATUS_COMPLETE
        job.completed_at = _now_iso()
        final_phase = "任务已完成" if job.status == JOB_STATUS_COMPLETE else "任务已结束，存在失败或无效运行"
        self._record_progress(
            job,
            stage="complete" if job.status == JOB_STATUS_COMPLETE else "failed",
            phase=final_phase,
            event_type="job.completed",
            detail=f"最终状态: {job.status}",
            persist=False,
        )
        self.store.save(job)

    def _apply_result(self, job: JobRecord, result: dict[str, Any]) -> None:
        unit_rows = {row.get("unit_id"): row for row in result.get("cells") or result.get("runs") or []}
        for unit in job.units:
            row = unit_rows.get(unit.unit_id)
            if row is None:
                if job.cancel_requested and unit.status in {UNIT_STATUS_QUEUED, UNIT_STATUS_RUNNING}:
                    unit.status = UNIT_STATUS_CANCELLED
                continue
            unit.run_id = row.get("run_id") or unit.run_id
            unit.actual_agent_steps = int(row.get("actual_agent_steps") or row.get("actual_steps") or 0)
            unit.stop_reason = str(row.get("stop_reason") or "")
            unit.duration_ms = int(row.get("duration_ms") or 0)
            # 模板运行没有 task_success（由 validity/停止原因表达结果）。保留
            # None，前端才能按既有契约回退到 validity；bool(None) 会把所有
            # 正常模板运行错误显示为“未成功”。
            raw_task_success = row.get("task_success")
            unit.task_success = bool(raw_task_success) if raw_task_success is not None else None
            unit.validity = str(row.get("validity") or "")
            raw_error = row.get("error")
            unit.error = str(raw_error) if raw_error else None
            if unit.validity == "INVALID":
                unit.status = UNIT_STATUS_INVALID
                unit.error = unit.error or unit.stop_reason or "运行无效"
            elif unit.error:
                unit.status = UNIT_STATUS_FAILED
            else:
                unit.status = UNIT_STATUS_COMPLETE
        # 结果只保留公开摘要;上下文工件路径与哈希、逐单元指标
        job.result = {
            key: value
            for key, value in result.items()
            if key
            in {
                "test_type",
                "case_id",
                "case_version",
                "session_id",
                "session_version",
                "repeat_count",
                "max_agent_steps",
                "total_runs",
                "unit_count",
                "by_agent",
                "invalid_runs",
                "custom_conditions",
                "selected_tool_ids",
                "fixture_set_id",
                "execution_order",
                "frozen_artifact_hashes",
                "skipped_unit_ids",
                "stats",
                "fingerprint",
                # 压缩决策摘要(context-only 公开口径;不含正文)
                "compression_details",
                # 新压缩策略管线摘要(budgeted 系;纯计数,不含正文)
                "segment_pipelines",
                # 运行配置快照(阶段A3):配置体不含 gold,可进公开摘要
                "run_configs",
                "fixed_conditions",
                "fixed_conditions_hash",
                # 模板批次摘要(混合路线):模板标识/分类/自变量/按变体聚合
                "template_id",
                "template_version",
                "classification",
                "independent_variable",
                "by_variant",
                "run_count",
                "skipped_run_ids",
                # 作业级预算口径(§11.2):真实请求累计与终止原因
                "budget",
                "budget_terminated",
            }
        }
        # 逐次运行明细(脱敏投影):answer/tool_calls(工具名+参数+状态)/
        # 步数/停止原因;不含逐轮消息正文、Mock 返回摘要与 gold
        runs = result.get("runs")
        if isinstance(runs, list):
            job.result["runs"] = [_public_run_row(row) for row in runs if isinstance(row, dict)]
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


#: 逐次运行行的公开字段(脱敏口径):不含逐轮输入消息正文(系统提示/完整上下文)、
#: 治理审计全量与请求参数快照;逐步证据以 model_calls.responseSummary(模型
#: 自身的决策与返回摘录)与 tool_calls.resultSummary(模型当时看到的世界返回)
#: 呈现——均为模型自身接收/产出的内容,不含 gold 与评判配置
_RUN_ROW_PUBLIC_FIELDS = (
    "unit_id",
    "run_id",
    "variant_label",
    "repeat_index",
    "config_hash",
    "governance_profile",
    "answer",
    "stop_reason",
    "actual_agent_steps",
    "duration_ms",
    "validity",
    "error",
)
_TOOL_ROW_PUBLIC_FIELDS = (
    "sequence",
    "toolName",
    "arguments",
    "status",
    "durationMs",
    "auditCode",
    "fixtureHit",
    "modelCallSequence",
    "resultSummary",
)
#: 模型调用行的公开字段:responseSummary 含 decision/toolCalls/textExcerpt
#: (模型自己的返回),不含 messages 输入快照与请求参数三态(所有者下钻)
_MODEL_CALL_PUBLIC_FIELDS = (
    "sequence",
    "decision",
    "status",
    "durationMs",
    "inputTokens",
    "outputTokens",
    "responseSummary",
)


def _public_run_row(row: dict[str, Any]) -> dict[str, Any]:
    base = {key: row.get(key) for key in _RUN_ROW_PUBLIC_FIELDS if key in row}
    tools = row.get("tool_calls")
    base["tool_calls"] = (
        [
            {key: item.get(key) for key in _TOOL_ROW_PUBLIC_FIELDS if key in item}
            for item in tools
            if isinstance(item, dict)
        ]
        if isinstance(tools, list)
        else []
    )
    model_calls = row.get("model_calls")
    base["model_calls"] = (
        [
            {key: item.get(key) for key in _MODEL_CALL_PUBLIC_FIELDS if key in item}
            for item in model_calls
            if isinstance(item, dict)
        ]
        if isinstance(model_calls, list)
        else []
    )
    return base


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
        # 变体数组/高级设置仍不可提交(由模板常量决定);
        # variant_label 允许在模板既有变体中选一个,发起恰好 1 次运行(单运行口径)
        "template_id",
        "preset_id",
        "variant_label",
    }
)


def _default_template_executor(
    job: JobRecord,
    *,
    should_stop: Callable[[], bool] = lambda: False,
    on_phase: Callable[[str], None] | None = None,
    on_run_done: Callable[[dict[str, Any]], None] | None = None,
    event_sink: Any | None = None,
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
    if on_phase is not None:
        on_phase("校验模板并装载固定用例、工具目录与冻结数据")
    repository = get_case_repository()
    case = repository.get_public_case(job.case_id)
    if case is None:
        raise PublicTestError(f"未知或非公开对比用例:{job.case_id}")
    # 按登记单元重建计划(修复:漏传 variant_labels 会导致单变体任务
    # 展开全部变体执行——登记与实际运行不一致)
    variant_labels = [unit.context_variant for unit in job.units if unit.context_variant] or None
    plan = plan_template_batch(
        job.template_id,
        repeat_count=job.repeat_count,
        role=ROLE_ANONYMOUS,
        preset_id=job.template_preset_id,
        variant_labels=variant_labels,
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
            on_run_done=on_run_done,
            event_sink=event_sink,
        )
    )
    # 单元对齐:_apply_result 按 unit_id 匹配,模板 run_id 即单元号
    result["runs"] = [dict(row, unit_id=row.get("run_id")) for row in result.get("runs") or []]
    return result


def _default_compression_executor(
    job: JobRecord,
    *,
    should_stop: Callable[[], bool] = lambda: False,
    on_phase: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """生产执行器(同步包装):压缩用例三个操作各自映射到 compression 模块。"""
    import asyncio

    from bdlh_runtime.experiments import compression as compression_module
    from bdlh_runtime.experiments import default_max_agent_steps

    assert job.session_id
    steps = job.max_agent_steps or default_max_agent_steps()
    if job.execution_scope == COMPRESSION_SCOPE_CONTEXT_ONLY:
        if on_phase is not None:
            on_phase("正在编译五份上下文工件(不运行 Agent)")
        result = compression_module.generate_contexts(job.session_id)
        session, _variants, _path = compression_module._load_session_bundle(job.session_id)
        return {
            "test_type": job.test_type,
            "session_id": result.session_id,
            "session_version": result.session_version,
            "fingerprint": result.fingerprint,
            "stats": result.stats,
            # 新压缩策略管线计数(budgeted 系;分段/命中/节省,公开口径无正文)
            "segment_pipelines": {
                vid: payload["segment_pipeline"]
                for vid, payload in result.artifacts.items()
                if payload.get("segment_pipeline")
            },
            # 决策摘要(公开口径):逐方式动作计数 + 被压缩/丢弃条目摘要(不含正文)
            "compression_details": compression_module.build_compression_details(
                result.artifacts, events=session.events
            ),
            "cells": [],  # 上下文生成阶段:0 个 Agent 运行
        }
    if job.execution_scope == COMPRESSION_SCOPE_CURRENT_COMBO:
        if on_phase is not None:
            on_phase("正在装载冻结上下文并运行 Agent")
        cell = asyncio.run(
            compression_module.run_current_combo(
                job.session_id,
                job.context_variant or "",
                NATIVE_AGENT_MODE_ID,
                max_agent_steps=steps,
            )
        )
        return {
            "cells": [cell.__dict__],
            "session_id": job.session_id,
            "frozen_artifact_hashes": {cell.context_variant: cell.context_artifact_hash},
        }
    if job.execution_scope == COMPRESSION_SCOPE_NATIVE_MATRIX:
        if on_phase is not None:
            on_phase("正在装载冻结上下文并逐单元运行 Agent")
        return asyncio.run(
            compression_module.run_native_context_matrix(
                job.session_id,
                max_agent_steps=steps,
                should_stop=should_stop,
            )
        )
    raise PublicTestError(f"未知压缩操作 execution_scope:{job.execution_scope!r}")
