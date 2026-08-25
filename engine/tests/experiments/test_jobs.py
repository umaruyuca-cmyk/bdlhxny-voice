"""匿名任务持久化测试:隔离、恢复、取消边界、publishable=false。"""

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


def _fake_comparison_executor(job):
    """伪造执行:3 个单元成功,其余按取消标志跳过。"""
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
            execution_scope="comparison-full",
            anonymous_id_hash=ANON_A,
            units=[JobUnit(seq=1, unit_id="u1", agent_mode_id="full-system", repeat_index=0)],
        )
        store.save(job)
        reloaded = JobStore(tmp_path / "jobs").get("job-x")
        assert reloaded is not None
        assert reloaded.units[0].agent_mode_id == "full-system"
        assert reloaded.anonymous_id_hash == ANON_A

    def test_anonymous_lists_only_own_jobs(self, tmp_path):
        store = JobStore(tmp_path / "jobs")
        for identity, job_id in ((ANON_A, "job-a1"), (ANON_A, "job-a2"), (ANON_B, "job-b1")):
            store.save(
                JobRecord(
                    job_id=job_id,
                    test_type=TestType.COMPARISON_CASE.value,
                    execution_scope="comparison-full",
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
            execution_scope="comparison-full",
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
            execution_scope="comparison-full",
            status=JOB_STATUS_QUEUED,
            anonymous_id_hash=ANON_A,
            units=[JobUnit(seq=1, unit_id="u1", agent_mode_id="a", repeat_index=0)],
        )
        done = JobRecord(
            job_id="job-done",
            test_type=TestType.COMPARISON_CASE.value,
            execution_scope="comparison-full",
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
    def test_create_comparison_job_nine_units(self, tmp_path):
        service = _service(tmp_path, comparison_executor=_fake_comparison_executor)
        job = service.create_job(
            {"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": 3},
            anonymous_id_hash=ANON_A,
        )
        assert len(job.units) == 9
        assert job.publishable is False  # 匿名运行固定不可发布
        stored = service.store.get(job.job_id)  # 同步线程工厂:读取落盘后的最终状态
        assert stored is not None
        assert stored.status == JOB_STATUS_COMPLETE
        assert stored.completed_unit_count() == 9

    def test_repeat_count_validated_backend(self, tmp_path):
        service = _service(tmp_path, comparison_executor=_fake_comparison_executor)
        with pytest.raises(PublicTestError):
            service.create_job(
                {"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": 4},
                anonymous_id_hash=ANON_A,
            )

    def test_forbidden_request_fields_rejected(self, tmp_path):
        """匿名接口不接受任意问题/系统提示/工具定义/Mock/模型地址/密钥。"""
        service = _service(tmp_path, comparison_executor=_fake_comparison_executor)
        for field in ("message", "prompt", "system_prompt", "tool_schema", "mock_result", "model_base_url", "api_key"):
            with pytest.raises(PublicTestError):
                service.create_job(
                    {"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": 3, field: "x"},
                    anonymous_id_hash=ANON_A,
                )

    def test_unknown_case_rejected(self, tmp_path):
        service = _service(tmp_path, comparison_executor=_fake_comparison_executor)
        with pytest.raises(PublicTestError):
            service.create_job(
                {"test_type": "COMPARISON_CASE", "case_id": "no-such", "repeat_count": 3},
                anonymous_id_hash=ANON_A,
            )

    def test_anonymous_cannot_read_others_jobs(self, tmp_path):
        service = _service(tmp_path, comparison_executor=_fake_comparison_executor)
        job = service.create_job(
            {"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": 3},
            anonymous_id_hash=ANON_A,
        )
        assert service.get_job_for(job.job_id, ANON_A).job_id == job.job_id
        with pytest.raises(PublicTestError):  # 匿名用户不能读取其他匿名任务
            service.get_job_for(job.job_id, ANON_B)
        with pytest.raises(PublicTestError):
            service.cancel_job(job.job_id, ANON_B)

    def test_cancel_blocks_only_unstarted_units(self, tmp_path):
        """执行中途取消:已开始的 3 个单元保留,未开始的 6 个不再执行。"""

        def executor(job):
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

        service = _service(tmp_path, comparison_executor=executor)
        job = service.create_job(
            {"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": 3},
            anonymous_id_hash=ANON_A,
        )
        stored = service.store.get(job.job_id)
        assert stored.completed_unit_count() == 3  # 已产生的运行与费用保留
        assert stored.status == JOB_STATUS_PARTIAL  # 部分完成,不显示为完整成功
        cancelled_units = [u for u in stored.units if u.status == UNIT_STATUS_CANCELLED]
        assert len(cancelled_units) == 6  # 未开始单元全部取消,不自动补跑

    def test_daily_quota_enforced(self, tmp_path):
        quota = PublicQuotaConfig(comparison_daily_jobs=2, daily_jobs_per_anonymous=10)
        service = _service(tmp_path, quota=quota, comparison_executor=_fake_comparison_executor)
        for _ in range(2):
            service.create_job(
                {"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": 3},
                anonymous_id_hash=ANON_A,
            )
        with pytest.raises(PublicTestError) as exc:
            service.create_job(
                {"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": 3},
                anonymous_id_hash=ANON_A,
            )
        assert "上限" in str(exc.value)
        # 其他匿名身份不受影响
        service.create_job(
            {"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": 3},
            anonymous_id_hash=ANON_B,
        )

    def test_concurrent_jobs_limited_per_anonymous(self, tmp_path):
        def slow_executor(job):
            stored = service.store.get(job.job_id)
            stored.status = JOB_STATUS_RUNNING
            service.store.save(stored)
            return _fake_comparison_executor(stored)

        service = _service(tmp_path, comparison_executor=slow_executor)
        service.create_job(
            {"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": 3},
            anonymous_id_hash=ANON_A,
        )
        # 手动把任务置回 RUNNING 模拟仍在执行
        stored = next(iter(service.store.list_for_anonymous(ANON_A)))
        stored.status = JOB_STATUS_RUNNING
        service.store.save(stored)
        with pytest.raises(PublicTestError):
            service.create_job(
                {"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": 3},
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

    def test_compression_full_matrix_twelve_units(self, tmp_path):
        def compression_executor(job, should_stop=lambda: False):
            return {
                "cells": [
                    {"unit_id": unit.unit_id, "task_success": True, "validity": "VALID",
                     "stop_reason": "FINAL_ANSWER", "actual_agent_steps": 1, "duration_ms": 5}
                    for unit in job.units[:6]
                ],  # 模拟中途取消:6 个完成,6 个未开始
                "unit_count": len(job.units),
            }

        service = _service(tmp_path, compression_executor=compression_executor)
        job = service.create_job(
            {
                "test_type": "COMPRESSION_CASE",
                "session_id": "ctx-session-context-engine-debug-01",
                "execution_scope": "full-matrix",
            },
            anonymous_id_hash=ANON_A,
        )
        assert len(job.units) == 12
        stored = service.store.get(job.job_id)
        assert stored.completed_unit_count() == 6
        # 取消/中断路径中未开始单元不再显示 QUEUED
        assert all(unit.status != UNIT_STATUS_QUEUED for unit in stored.units)

    def test_cancel_queued_job_cancels_all_units(self, tmp_path):
        """排队中的任务被取消:全部单元直接取消,不产生任何模型费用。"""
        service = _service(
            tmp_path,
            comparison_executor=lambda job: (_ for _ in ()).throw(AssertionError("不应执行")),
        )
        # 用异步线程工厂:创建后不立即执行
        service._thread_factory = lambda target: None
        job = service.create_job(
            {"test_type": "COMPARISON_CASE", "case_id": "cmp-x", "repeat_count": 3},
            anonymous_id_hash=ANON_A,
        )
        cancelled = service.cancel_job(job.job_id, ANON_A)
        assert cancelled.status == JOB_STATUS_CANCELLED
        assert all(unit.status == UNIT_STATUS_CANCELLED for unit in cancelled.units)
