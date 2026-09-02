"""新默认上下文运行计划测试(混合路线 D1)。

4×1(四种上下文 × 一种固定原生 Tool Calling 配置)是唯一运行计划。
全部使用 Fake 执行器与静态 Session 数据。
"""

from __future__ import annotations

import pytest

from bdlh_runtime.experiments import (
    COMPRESSION_SCOPE_NATIVE_MATRIX,
    NATIVE_AGENT_MODE_ID,
    TestType,
    native_context_run_count,
    plan_native_context_runs,
)
from bdlh_runtime.experiments import compression as compression_module
from bdlh_runtime.experiments.compression import (
    COMPRESSION_SESSIONS,
    build_compression_run_configs,
    compile_variants,
    run_native_context_matrix,
)

SESSION_ID = COMPRESSION_SESSIONS[1][0]  # 最小的 Session


def test_native_plan_is_4x1_not_8_cells():
    units = plan_native_context_runs("preview")
    assert len(units) == 4
    assert {unit.agent_mode_id for unit in units} == {NATIVE_AGENT_MODE_ID}
    assert len({unit.context_variant for unit in units}) == 4  # 唯一自变量:上下文方式
    assert native_context_run_count() == 4


@pytest.mark.asyncio
async def test_run_native_context_matrix_uses_frozen_artifacts_and_configs():
    session, variants, _ = compression_module._load_session_bundle(SESSION_ID)
    compiled = compile_variants(session, variants)
    spy: list[tuple[str, str]] = []

    async def fake_runner(session, artifact, agent_mode_id, run_key, max_agent_steps, *, llm=None):
        spy.append((str(artifact.variant_id), agent_mode_id))
        return {
            "answer": "ok",
            "error": None,
            "tool_calls": [],
            "stop_reason": "FINAL_ANSWER",
            "actual_agent_steps": 1,
            "duration_ms": 1,
        }

    result = await run_native_context_matrix(SESSION_ID, artifacts=compiled, cell_runner=fake_runner, max_agent_steps=4)
    assert result["unit_count"] == 4
    assert len(result["cells"]) == 4
    assert {mode for _v, mode in spy} == {NATIVE_AGENT_MODE_ID}
    # 每格配置快照:唯一自变量 context_strategy,其余字段一致
    assert set(result["run_configs"]) == {
        f"{SESSION_ID}:{variant}:{NATIVE_AGENT_MODE_ID}"
        for variant in ("full", "recent-turns", "single-summary", "budgeted-hybrid-v1")
    }
    strategies = {payload["context_strategy"] for payload in result["run_configs"].values()}
    assert len(strategies) == 4
    for payload in result["run_configs"].values():
        assert payload["execution_engine"] == "native-tool-calling"
    assert result["fixed_conditions"]["experiment_definition"] == "context-strategy-comparison"
    assert result["fixed_conditions"]["independent_variable"] == ["context_strategy"]
    assert result["fixed_conditions"]["agent_mode_ids"] == [NATIVE_AGENT_MODE_ID]
    assert result["fixed_conditions_hash"]


def test_native_run_configs_pass_formal_validation():
    session, variants, _ = compression_module._load_session_bundle(SESSION_ID)
    compiled = compile_variants(session, variants)
    configs = build_compression_run_configs(session, compiled, 4, agent_mode_ids=(NATIVE_AGENT_MODE_ID,))
    assert len(configs) == 4
    for config in configs.values():
        config.validate_for_formal_template()  # native 配置满足正式模板边界


def test_public_service_closes_native_matrix_scope(tmp_path):
    """一次只运行一个 Agent(P0-1):匿名服务的 native-matrix 一次四运行入口关闭。"""
    from bdlh_runtime.experiments.job_store import JobStore
    from bdlh_runtime.experiments.public_service import AnonymousJobService, PublicTestError

    store = JobStore(root=tmp_path)
    service = AnonymousJobService(
        store,
        quota=_quota(),
        thread_factory=lambda target: None,  # 不真正起线程
    )
    with pytest.raises(PublicTestError) as excinfo:
        service._create_compression_job(
            {
                "test_type": TestType.COMPRESSION_CASE.value,
                "session_id": SESSION_ID,
                "execution_scope": COMPRESSION_SCOPE_NATIVE_MATRIX,
                "repeat_count": 1,
            },
            job_id="job-native-test",
        )
    assert "入口已关闭" in str(excinfo.value)


def _quota():
    from bdlh_runtime.experiments.quota import PublicQuotaConfig

    return PublicQuotaConfig.from_env()
