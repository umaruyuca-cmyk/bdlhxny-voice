"""领域模型口径测试:repeat_count 校验、运行展开与数量口径。"""

from __future__ import annotations

import pytest

from bdlh_runtime.experiments import (
    COMPARISON_REPEAT_COUNTS,
    CONTEXT_MATRIX_MODES,
    NATIVE_AGENT_MODE_ID,
    RepeatCountError,
    TestType,
    default_max_agent_steps,
    native_context_run_count,
    plan_native_context_runs,
    theoretical_max_model_calls,
    validate_repeat_count,
)


class TestRepeatCountValidation:
    def test_comparison_accepts_only_3_or_5(self):
        assert validate_repeat_count(TestType.COMPARISON_CASE, 3) == 3
        assert validate_repeat_count(TestType.COMPARISON_CASE, 5) == 5
        for bad in (1, 2, 4, 6, 10, 0, -1):
            with pytest.raises(RepeatCountError):
                validate_repeat_count(TestType.COMPARISON_CASE, bad)

    def test_comparison_rejects_non_integer(self):
        with pytest.raises(RepeatCountError):
            validate_repeat_count(TestType.COMPARISON_CASE, "3")  # type: ignore[arg-type]
        with pytest.raises(RepeatCountError):
            validate_repeat_count(TestType.COMPARISON_CASE, True)

    def test_compression_fixed_at_one(self):
        assert validate_repeat_count(TestType.COMPRESSION_CASE, 1) == 1
        for bad in (2, 3, 5, 0):
            with pytest.raises(RepeatCountError):
                validate_repeat_count(TestType.COMPRESSION_CASE, bad)

    def test_repeat_options_match_rule(self):
        assert COMPARISON_REPEAT_COUNTS == (3, 5)


class TestRunExpansion:
    def test_one_session_expands_to_4x1_cells_each_once(self):
        units = plan_native_context_runs("sess-x")
        assert len(units) == 4
        assert native_context_run_count() == 4
        # 唯一自变量是上下文方式:4 方式 × 1 种统一原生配置,每格 repeat_index=0
        # 矩阵口径 4×1:抽取式基线不在 Agent 矩阵(与主算法冻结工件相同)
        assert {u.context_variant for u in units} == set(CONTEXT_MATRIX_MODES)
        assert {u.agent_mode_id for u in units} == {NATIVE_AGENT_MODE_ID}
        assert all(u.repeat_index == 0 for u in units)
        assert all(u.test_type is TestType.COMPRESSION_CASE for u in units)
        assert len({u.unit_id for u in units}) == 4

    def test_theoretical_model_calls_display(self):
        assert theoretical_max_model_calls(12, 5) == 60
        assert theoretical_max_model_calls(9, 3) == 27

    def test_max_agent_steps_from_env(self, monkeypatch):
        monkeypatch.delenv("MAX_AGENT_STEPS", raising=False)
        assert default_max_agent_steps() == 8
        monkeypatch.setenv("MAX_AGENT_STEPS", "5")
        assert default_max_agent_steps() == 5
        monkeypatch.setenv("MAX_AGENT_STEPS", "bogus")
        assert default_max_agent_steps() == 8
