"""匿名任务持久化测试:隔离、恢复、取消边界、publishable=false。

一次只运行一个 Agent(P0-1):匿名多运行入口(模板变体展开、native-matrix)
已明确关闭;单运行任务走「运行当前组合」(1 个单元),执行器注入 Fake,
不调用真实 LLM。
"""

from __future__ import annotations

import pytest

from bdlh_runtime.experiments import TestType
from bdlh_runtime.experiments.comparison import ComparisonCase
from bdlh_runtime.experiments.job_store import (
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETE,
    JOB_STATUS_INTERRUPTED,
    JOB_STATUS_PARTIAL,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    UNIT_STATUS_CANCELLED,
    UNIT_STATUS_COMPLETE,
    UNIT_STATUS_INTERRUPTED,
    UNIT_STATUS_QUEUED,
    UNIT_STATUS_RUNNING,
    JobRecord,
    JobStore,
    JobUnit,
    sha256_hex,
)
from bdlh_runtime.experiments.judge import CallRelationSpec
from bdlh_runtime.experiments.public_service import AnonymousJobService, PublicTestError
from bdlh_runtime.experiments.quota import PublicQuotaConfig

#: 匿名可用的对比模板:2 个治理变体 × repeat_count → 运行单元
TEMPLATE_ID = "governance-on-off"


class MemoryRepo:
    def __init__(self, cases: list[ComparisonCase]):
        self._cases = cases

    def get_public_case(self, case_id: str) -> ComparisonCase | None:
        return next((case for case in self._cases if case.case_id == case_id), None)


def _case(case_id: str = "cmp-x") -> ComparisonCase:
    return ComparisonCase(
        case_id=case_id,
        case_version=1,
        title="t",
        message="m",
        scene="general",
        allowed_tools=("a.tool", "b.tool"),
        default_visible_tools=("a.tool", "b.tool"),
        fixture_set_id="cmp-fixtures-v1",
        call_relation=CallRelationSpec(),
    )


def _sync_thread(target):
    """测试用「线程工厂」:直接同步执行,保证断言时任务已完成。"""
    target()
    return None


def _service(tmp_path, **kwargs) -> AnonymousJobService:
    store = JobStore(tmp_path / "jobs")
    defaults = dict(
        case_repository=MemoryRepo([_case()]),
        quota=PublicQuotaConfig(),
        thread_factory=_sync_thread,
    )
    defaults.update(kwargs)
    return AnonymousJobService(store, **defaults)


def _fake_template_executor(job, should_stop=lambda: False):
    """伪造模板执行:3 个单元成功,其余按取消标志跳过。"""
    runs = []
    for index, unit in enumerate(job.units):
        if job.cancel_requested and index >= 3:
            break
        runs.append(
            {
                "unit_id": unit.unit_id,
                "task_success": True,
                "validity": "VALID",
                "stop_reason": "FINAL_ANSWER",
                "actual_agent_steps": 2,
                "duration_ms": 10,
            }
        )
    return {"runs": runs, "total_runs": len(job.units), "test_type": job.test_type}


ANON_A = sha256_hex("cookie-aaa")
ANON_B = sha256_hex("cookie-bbb")


class TestJobStore:
    def test_persist_and_reload(self, tmp_path):
        store = JobStore(tmp_path / "jobs")
        job = JobRecord(
            job_id="job-x",
            test_type=TestType.COMPARISON_CASE.value,
            execution_scope="template-batch",
            anonymous_id_hash=ANON_A,
            units=[JobUnit(seq=1, unit_id="u1", agent_mode_id="native-tool-calling", repeat_index=0)],
        )
        store.save(job)
        reloaded = JobStore(tmp_path / "jobs").get("job-x")
        assert reloaded is not None
        assert reloaded.units[0].agent_mode_id == "native-tool-calling"
        assert reloaded.anonymous_id_hash == ANON_A

    def test_anonymous_lists_only_own_jobs(self, tmp_path):
        store = JobStore(tmp_path / "jobs")
        for identity, job_id in ((ANON_A, "job-a1"), (ANON_A, "job-a2"), (ANON_B, "job-b1")):
            store.save(
                JobRecord(
                    job_id=job_id,
                    test_type=TestType.COMPARISON_CASE.value,
                    execution_scope="template-batch",
                    anonymous_id_hash=identity,
                )
            )
        assert [job.job_id for job in store.list_for_anonymous(ANON_A)] == ["job-a2", "job-a1"]
        assert [job.job_id for job in store.list_for_anonymous(ANON_B)] == ["job-b1"]

    def test_recover_interrupted_marks_active_jobs(self, tmp_path):
        store = JobStore(tmp_path / "jobs")
        running = JobRecord(
            job_id="job-running",
            test_type=TestType.COMPARISON_CASE.value,
            execution_scope="template-batch",
            status=JOB_STATUS_RUNNING,
            anonymous_id_hash=ANON_A,
            units=[
                JobUnit(seq=1, unit_id="u1", agent_mode_id="a", repeat_index=0, status=UNIT_STATUS_COMPLETE),
                JobUnit(seq=2, unit_id="u2", agent_mode_id="b", repeat_index=0, status=UNIT_STATUS_RUNNING),
                JobUnit(seq=3, unit_id="u3", agent_mode_id="c", repeat_index=0, status=UNIT_STATUS_QUEUED),
            ],
        )
        queued = JobRecord(
            job_id="job-queued",
            test_type=TestType.COMPARISON_CASE.value,
            execution_scope="template-batch",
            status=JOB_STATUS_QUEUED,
            anonymous_id_hash=ANON_A,
            units=[JobUnit(seq=1, unit_id="u1", agent_mode_id="a", repeat_index=0)],
        )
        done = JobRecord(
            job_id="job-done",
            test_type=TestType.COMPARISON_CASE.value,
            execution_scope="template-batch",
            status=JOB_STATUS_COMPLETE,
            anonymous_id_hash=ANON_A,
        )
        for job in (running, queued, done):
            store.save(job)

        interrupted = store.recover_interrupted()
        assert set(interrupted) == {"job-running", "job-queued"}

        re_running = store.get("job-running")
        assert re_running.status == JOB_STATUS_INTERRUPTED  # 服务重启后不能永久显示运行中
        assert re_running.units[0].status == UNIT_STATUS_COMPLETE  # 已完成单元保持不变
        assert re_running.units[1].status == UNIT_STATUS_INTERRUPTED
        assert re_running.units[2].status == UNIT_STATUS_INTERRUPTED  # 未开始也标记中断,不自动重跑

        re_queued = store.get("job-queued")
        assert re_queued.status == JOB_STATUS_INTERRUPTED  # 未开始的任务同样标记中断
        assert store.get("job-done").status == JOB_STATUS_COMPLETE  # 完成任务不受影响


class TestAnonymousService:
    def test_create_template_comparison_job_rejects_multi_run(self, tmp_path):
        """一次只运行一个 Agent(P0-1):匿名模板任务不再展开 2 变体 × repeat。

        多运行入口明确关闭(不保留隐式批量执行);匿名详情只允许 0/1 个单元
        的路径(压缩上下文生成、运行当前组合、单变体 1 次运行)。
        """
        service = _service(tmp_path, template_executor=_fake_template_executor)
        with pytest.raises(PublicTestError) as exc:
            service.create_job(
                {"test_type": "COMPARISON_CASE", "template_id": TEMPLATE_ID, "case_id": "cmp-x", "repeat_count": 3},
                anonymous_id_hash=ANON_A,
            )
        assert "入口已关闭" in str(exc.value)

    def test_create_template_job_single_variant_one_unit(self, tmp_path):
        """匿名单变体口径:variant_label 在模板变体中选择,恰好 1 个运行单元。"""
        service = _service(tmp_path, template_executor=_fake_template_executor)
        job = service.create_job(
            {
                "test_type": "COMPARISON_CASE",
                "template_id": TEMPLATE_ID,
                "case_id": "cmp-x",
                "repeat_count": 1,
                "variant_label": "off",
            },
            anonymous_id_hash=ANON_A,
        )
        assert len(job.units) == 1
        assert job.units[0].context_variant == "off"
        assert job.publishable is False  # 匿名运行固定不可发布
        stored = service.store.get(job.job_id)  # 同步线程工厂:读取落盘后的最终状态
        assert stored is not None
        assert stored.status == JOB_STATUS_COMPLETE
        assert stored.completed_unit_count() == 1

    def test_single_variant_rejects_repeat_gt_one(self, tmp_path):
        """匿名单变体运行固定 1 次;重复多次不予创建。"""
        service = _service(tmp_path, template_executor=_fake_template_executor)
        with pytest.raises(PublicTestError, match="固定 1 次"):
            service.create_job(
                {
                    "test_type": "COMPARISON_CASE",
                    "template_id": TEMPLATE_ID,
                    "case_id": "cmp-x",
                    "repeat_count": 3,
                    "variant_label": "standard",
                },
                anonymous_id_hash=ANON_A,
            )

    def _current_combo_payload(self, **over):
        """单运行匿名任务(1 个 Agent 运行):运行当前组合。"""
        body = {
            "test_type": "COMPRESSION_CASE",
            "session_id": "ctx-session-context-engine-debug-01",
            "execution_scope": "current-combo",
            "context_variant": "full-session",
            "agent_mode_id": "native-tool-calling",
        }
        body.update(over)
        return body

    def test_comparison_without_template_rejected(self, tmp_path):
        """对比任务必须携带 template_id:缺 template_id 一律拒绝。"""
        service = _service(tmp_path, template_executor=_fake_template_executor)
        with pytest.raises(PublicTestError, match="模板"):
            service.create_job(
                {"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": 3},
                anonymous_id_hash=ANON_A,
            )

    def test_repeat_count_validated_backend(self, tmp_path):
        service = _service(tmp_path, template_executor=_fake_template_executor)
        with pytest.raises(PublicTestError, match="repeat_count"):
            service.create_job(
                {"test_type": "COMPARISON_CASE", "template_id": TEMPLATE_ID, "case_id": "cmp-x", "repeat_count": 6},
                anonymous_id_hash=ANON_A,
            )

    def test_forbidden_request_fields_rejected(self, tmp_path):
        """匿名接口不接受任意问题/系统提示/工具定义/Mock/模型地址/密钥。"""
        service = _service(tmp_path, template_executor=_fake_template_executor)
        for field in ("message", "prompt", "system_prompt", "tool_schema", "mock_result", "model_base_url", "api_key"):
            with pytest.raises(PublicTestError):
                service.create_job(
                    {
                        "test_type": "COMPARISON_CASE",
                        "template_id": TEMPLATE_ID,
                        "case_id": "cmp-x",
                        "repeat_count": 3,
                        field: "x",
                    },
                    anonymous_id_hash=ANON_A,
                )

    def test_unknown_case_rejected(self, tmp_path):
        service = _service(tmp_path, template_executor=_fake_template_executor)
        with pytest.raises(PublicTestError):
            service.create_job(
                {"test_type": "COMPARISON_CASE", "template_id": TEMPLATE_ID, "case_id": "no-such", "repeat_count": 3},
                anonymous_id_hash=ANON_A,
            )

    def test_anonymous_cannot_read_others_jobs(self, tmp_path):
        def combo_executor(job, should_stop=lambda: False):
            return {
                "cells": [
                    {
                        "unit_id": unit.unit_id,
                        "task_success": True,
                        "validity": "VALID",
                        "stop_reason": "FINAL_ANSWER",
                        "actual_agent_steps": 1,
                        "duration_ms": 5,
                    }
                    for unit in job.units
                ],
                "unit_count": len(job.units),
            }

        service = _service(tmp_path, compression_executor=combo_executor)
        job = service.create_job(self._current_combo_payload(), anonymous_id_hash=ANON_A)
        assert service.get_job_for(job.job_id, ANON_A).job_id == job.job_id
        with pytest.raises(PublicTestError):  # 匿名用户不能读取其他匿名任务
            service.get_job_for(job.job_id, ANON_B)
        with pytest.raises(PublicTestError):
            service.cancel_job(job.job_id, ANON_B)

    def test_cancel_blocks_only_unstarted_units(self, tmp_path):
        """执行中途取消:已开始的单元保留,未开始的不再执行(执行器机制)。

        创建入口已不产生多单元任务(P0-1);本测试直接构造多单元记录,
        验证 execute/取消机制对既有数据仍保持正确语义。
        """
        units = [
            JobUnit(
                seq=index + 1,
                unit_id=f"u{index + 1}",
                agent_mode_id="native-tool-calling",
                repeat_index=0,
                status=UNIT_STATUS_QUEUED,
            )
            for index in range(6)
        ]
        record = JobRecord(
            job_id="job-cancel-01",
            test_type=TestType.COMPARISON_CASE.value,
            execution_scope="template-batch",
            template_id=TEMPLATE_ID,
            status=JOB_STATUS_QUEUED,
            anonymous_id_hash=ANON_A,
            units=units,
        )

        def executor(job, should_stop=lambda: False):
            runs = []
            for index, unit in enumerate(job.units):
                if job.cancel_requested and index >= 3:  # 取消只阻止尚未开始的单元
                    break
                runs.append(
                    {
                        "unit_id": unit.unit_id,
                        "task_success": True,
                        "validity": "VALID",
                        "stop_reason": "FINAL_ANSWER",
                        "actual_agent_steps": 2,
                        "duration_ms": 10,
                    }
                )
                if index == 2:  # 第 3 个单元完成后用户点击取消
                    stored = service.store.get(job.job_id)
                    stored.cancel_requested = True
                    job.cancel_requested = True
            return {"runs": runs, "total_runs": len(job.units), "test_type": job.test_type}

        service = _service(tmp_path, template_executor=executor)
        service.store.save(record)
        service.execute(record.job_id)
        stored = service.store.get(record.job_id)
        assert stored.completed_unit_count() == 3  # 已产生的运行与费用保留
        assert stored.status == JOB_STATUS_PARTIAL  # 部分完成,不显示为完整成功
        cancelled_units = [u for u in stored.units if u.status == UNIT_STATUS_CANCELLED]
        assert len(cancelled_units) == 3  # 未开始单元全部取消,不自动补跑

    def test_daily_quota_enforced(self, tmp_path):
        quota = PublicQuotaConfig(compression_context_daily_jobs=2)
        service = _service(tmp_path, quota=quota, compression_executor=lambda job, should_stop=lambda: False: {})
        for _ in range(2):
            service.create_job(
                {
                    "test_type": "COMPRESSION_CASE",
                    "session_id": "ctx-session-context-engine-debug-01",
                    "execution_scope": "context-only",
                },
                anonymous_id_hash=ANON_A,
            )
        with pytest.raises(PublicTestError) as exc:
            service.create_job(
                {
                    "test_type": "COMPRESSION_CASE",
                    "session_id": "ctx-session-context-engine-debug-01",
                    "execution_scope": "context-only",
                },
                anonymous_id_hash=ANON_A,
            )
        assert "上限" in str(exc.value)
        # 其他匿名身份不受影响
        service.create_job(
            {
                "test_type": "COMPRESSION_CASE",
                "session_id": "ctx-session-context-engine-debug-01",
                "execution_scope": "context-only",
            },
            anonymous_id_hash=ANON_B,
        )

    def test_concurrent_jobs_limited_per_anonymous(self, tmp_path):
        def slow_executor(job, should_stop=lambda: False):
            stored = service.store.get(job.job_id)
            stored.status = JOB_STATUS_RUNNING
            service.store.save(stored)
            return {"cells": [], "stats": {}, "test_type": job.test_type}

        service = _service(tmp_path, compression_executor=slow_executor)
        service.create_job(
            {
                "test_type": "COMPRESSION_CASE",
                "session_id": "ctx-session-context-engine-debug-01",
                "execution_scope": "context-only",
            },
            anonymous_id_hash=ANON_A,
        )
        # 手动把任务置回 RUNNING 模拟仍在执行
        stored = next(iter(service.store.list_for_anonymous(ANON_A)))
        stored.status = JOB_STATUS_RUNNING
        service.store.save(stored)
        with pytest.raises(PublicTestError):
            service.create_job(
                {
                    "test_type": "COMPRESSION_CASE",
                    "session_id": "ctx-session-context-engine-debug-01",
                    "execution_scope": "context-only",
                },
                anonymous_id_hash=ANON_A,
            )

    def test_compression_context_only_creates_zero_agent_units(self, tmp_path):
        def compression_executor(job, should_stop=lambda: False):
            return {"cells": [], "stats": {"variant_count": 4}, "test_type": job.test_type}

        service = _service(tmp_path, compression_executor=compression_executor)
        job = service.create_job(
            {
                "test_type": "COMPRESSION_CASE",
                "session_id": "ctx-session-context-engine-debug-01",
                "execution_scope": "context-only",
            },
            anonymous_id_hash=ANON_A,
        )
        assert job.units == []  # 只生成上下文:0 个 Agent 运行单元
        stored = service.store.get(job.job_id)
        assert stored.result.get("stats", {}).get("variant_count") == 4

    def test_compression_native_matrix_entry_closed(self, tmp_path):
        """一次只运行一个 Agent(P0-1):native-matrix 一次四运行入口关闭。"""
        service = _service(tmp_path, compression_executor=lambda job, should_stop=lambda: False: {})
        with pytest.raises(PublicTestError) as excinfo:
            service.create_job(
                {
                    "test_type": "COMPRESSION_CASE",
                    "session_id": "ctx-session-context-engine-debug-01",
                    "execution_scope": "native-matrix",
                },
                anonymous_id_hash=ANON_A,
            )
        assert "入口已关闭" in str(excinfo.value)

    def test_template_compression_context_only_zero_units(self, tmp_path):
        """长上下文模板 × context-only:委托压缩链,0 个 Agent 单元,记录模板口径。"""

        def compression_executor(job, should_stop=lambda: False):
            return {
                "cells": [],
                "stats": {"variant_count": 4},
                "compression_details": {"budgeted-session": {"counts": {"kept": 9}}},
                "test_type": job.test_type,
            }

        service = _service(tmp_path, compression_executor=compression_executor)
        job = service.create_job(
            {
                "test_type": "COMPRESSION_CASE",
                "template_id": "context-strategy-comparison",
                "session_id": "ctx-session-context-engine-debug-01",
                "execution_scope": "context-only",
                "repeat_count": 1,
            },
            anonymous_id_hash=ANON_A,
        )
        assert job.units == []
        assert job.template_id == "context-strategy-comparison"
        stored = service.store.get(job.job_id)  # 同步线程工厂:读落盘终态
        assert stored.status == JOB_STATUS_COMPLETE
        assert stored.result.get("stats", {}).get("variant_count") == 4
        # 决策摘要在公开结果白名单内,匿名详情页可见
        assert stored.result.get("compression_details") == {"budgeted-session": {"counts": {"kept": 9}}}

    def test_template_compression_native_matrix_entry_closed(self, tmp_path):
        """长上下文模板 × native-matrix:同样关闭(委托压缩链前先拒绝)。"""
        seen_executors = []

        service = _service(
            tmp_path,
            compression_executor=lambda job, should_stop=False: seen_executors.append("compression") or {},
            template_executor=lambda job, should_stop=lambda: False: (_ for _ in ()).throw(
                AssertionError("关闭的入口不应触达任何执行器")
            ),
        )
        with pytest.raises(PublicTestError) as excinfo:
            service.create_job(
                {
                    "test_type": "COMPRESSION_CASE",
                    "template_id": "context-strategy-comparison",
                    "session_id": "ctx-session-context-engine-debug-01",
                    "execution_scope": "native-matrix",
                    "repeat_count": 1,
                },
                anonymous_id_hash=ANON_A,
            )
        assert "入口已关闭" in str(excinfo.value)
        assert seen_executors == []

    def test_cancel_queued_job_cancels_all_units(self, tmp_path):
        """排队中的任务被取消:全部单元直接取消,不产生任何模型费用。"""
        service = _service(
            tmp_path,
            compression_executor=lambda job, should_stop=lambda: False: (_ for _ in ()).throw(
                AssertionError("不应执行")
            ),
        )
        # 用异步线程工厂:创建后不立即执行
        service._thread_factory = lambda target: None
        job = service.create_job(
            {
                "test_type": "COMPRESSION_CASE",
                "session_id": "ctx-session-context-engine-debug-01",
                "execution_scope": "current-combo",
                "context_variant": "full-session",
                "agent_mode_id": "native-tool-calling",
            },
            anonymous_id_hash=ANON_A,
        )
        cancelled = service.cancel_job(job.job_id, ANON_A)
        assert cancelled.status == JOB_STATUS_CANCELLED
        assert all(unit.status == UNIT_STATUS_CANCELLED for unit in cancelled.units)


# ── 幂等(P0-4)──────────────────────────────────────────────────────────


class TestIdempotency:
    def _payload(self, **over):
        """单运行匿名任务(current-combo:1 个 Agent 运行)。"""
        body = {
            "test_type": "COMPRESSION_CASE",
            "session_id": "ctx-session-context-engine-debug-01",
            "execution_scope": "current-combo",
            "context_variant": "full-session",
            "agent_mode_id": "native-tool-calling",
        }
        body.update(over)
        return body

    def test_same_key_same_body_returns_original_job(self, tmp_path):
        service = _service(tmp_path, compression_executor=lambda job, should_stop=lambda: False: {})
        job1 = service.create_job(self._payload(idempotency_key="key-aaaaaaaa-1"), anonymous_id_hash=ANON_A)
        job2 = service.create_job(self._payload(idempotency_key="key-aaaaaaaa-1"), anonymous_id_hash=ANON_A)
        assert job1.job_id == job2.job_id  # 重试/并发提交不创建第二个任务

    def test_same_key_different_body_conflicts(self, tmp_path):
        from bdlh_runtime.experiments.public_service import IdempotencyConflict

        service = _service(tmp_path, compression_executor=lambda job, should_stop=lambda: False: {})
        service.create_job(self._payload(idempotency_key="key-bbbbbbbb-1"), anonymous_id_hash=ANON_A)
        with pytest.raises(IdempotencyConflict):
            service.create_job(
                self._payload(idempotency_key="key-bbbbbbbb-1", context_variant="recent-window"),
                anonymous_id_hash=ANON_A,
            )

    def test_same_key_different_identity_not_shared(self, tmp_path):
        service = _service(tmp_path, compression_executor=lambda job, should_stop=lambda: False: {})
        job_a = service.create_job(self._payload(idempotency_key="key-cccccccc-1"), anonymous_id_hash=ANON_A)
        job_b = service.create_job(self._payload(idempotency_key="key-cccccccc-1"), anonymous_id_hash=ANON_B)
        assert job_a.job_id != job_b.job_id  # 不同匿名身份互不串用

    def test_invalid_key_length_rejected(self, tmp_path):
        service = _service(tmp_path, compression_executor=lambda job, should_stop=lambda: False: {})
        with pytest.raises(PublicTestError, match="idempotency_key"):
            service.create_job(self._payload(idempotency_key="short"), anonymous_id_hash=ANON_A)


# ── 历史数据审计(修复方案 §15)─────────────────────────────────────────


class TestInvalidAgentRunAudit:
    def test_zero_step_complete_units_marked_invalid(self, tmp_path):
        """COMPLETE 且 actual_agent_steps=0 的单元 → INVALID + 原因保留,答案不改。"""
        store = JobStore(tmp_path / "jobs")
        unit = JobUnit(
            seq=1,
            unit_id="u1",
            agent_mode_id="a",
            repeat_index=0,
            status=UNIT_STATUS_COMPLETE,
            actual_agent_steps=0,
            task_success=True,
        )
        healthy = JobUnit(
            seq=2,
            unit_id="u2",
            agent_mode_id="b",
            repeat_index=0,
            status=UNIT_STATUS_COMPLETE,
            actual_agent_steps=2,
            task_success=True,
        )
        job = JobRecord(
            job_id="job-audit-1",
            test_type=TestType.COMPARISON_CASE.value,
            execution_scope="template-batch",
            anonymous_id_hash=ANON_A,
            units=[unit, healthy],
        )
        store.save(job)
        audited = store.audit_invalid_agent_runs()
        assert audited == ["job-audit-1"]
        stored = store.get("job-audit-1")
        suspect = stored.units[0]
        assert suspect.validity == "INVALID"
        assert "LLM_UNAVAILABLE" in suspect.summary["measurement_invalid_reason"]
        assert stored.units[1].validity == ""  # 正常单元不受影响
        assert stored.result["measurement_invalid"] is True
        assert stored.result["measurement_invalid_unit_ids"] == ["u1"]

    def test_audit_is_idempotent(self, tmp_path):
        store = JobStore(tmp_path / "jobs")
        job = JobRecord(
            job_id="job-audit-2",
            test_type=TestType.COMPARISON_CASE.value,
            execution_scope="template-batch",
            anonymous_id_hash=ANON_A,
            units=[
                JobUnit(
                    seq=1,
                    unit_id="u1",
                    agent_mode_id="a",
                    repeat_index=0,
                    status=UNIT_STATUS_COMPLETE,
                    actual_agent_steps=0,
                )
            ],
        )
        store.save(job)
        assert store.audit_invalid_agent_runs() == ["job-audit-2"]
        assert store.audit_invalid_agent_runs() == []  # 已审计任务不再重复处理

    def test_healthy_jobs_untouched(self, tmp_path):
        store = JobStore(tmp_path / "jobs")
        store.save(
            JobRecord(
                job_id="job-fine",
                test_type=TestType.COMPARISON_CASE.value,
                execution_scope="template-batch",
                anonymous_id_hash=ANON_A,
                units=[
                    JobUnit(
                        seq=1,
                        unit_id="u1",
                        agent_mode_id="a",
                        repeat_index=0,
                        status=UNIT_STATUS_COMPLETE,
                        actual_agent_steps=3,
                    )
                ],
            )
        )
        assert store.audit_invalid_agent_runs() == []
