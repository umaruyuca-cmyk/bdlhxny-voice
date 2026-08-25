"""领域模型口径测试:repeat_count 校验、运行展开、轮转顺序与数量口径。"""

from __future__ import annotations

import pytest

from bdlh_runtime.experiments import (
    AGENT_MODE_IDS,
    COMPARISON_REPEAT_COUNTS,
    RepeatCountError,
    TestType,
    comparison_run_count,
    compression_all_sessions_run_count,
    compression_session_run_count,
    default_max_agent_steps,
    plan_comparison_runs,
    plan_compression_matrix,
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
    def test_one_case_expands_to_9_runs(self):
        units = plan_comparison_runs("cmp-x", 3)
        assert len(units) == 9
        assert comparison_run_count(3) == 9

    def test_one_case_expands_to_15_runs(self):
        units = plan_comparison_runs("cmp-x", 5)
        assert len(units) == 15
        assert comparison_run_count(5) == 15

    def test_three_agent_modes_in_every_repeat_group(self):
        units = plan_comparison_runs("cmp-x", 5)
        for group_index in range(5):
            group = units[group_index * 3 : group_index * 3 + 3]
            assert {unit.agent_mode_id for unit in group} == set(AGENT_MODE_IDS)
            assert [unit.repeat_index for unit in group] == [group_index] * 3

    def test_agent_order_rotates_by_repeat_index(self):
        units = plan_comparison_runs("cmp-x", 3)
        first = [u.agent_mode_id for u in units[0:3]]
        second = [u.agent_mode_id for u in units[3:6]]
        third = [u.agent_mode_id for u in units[6:9]]
        # 第 1 组 A→B→C;第 2 组 B→C→A;第 3 组 C→A→B(避免同一实现总是先运行)
        assert first == ["baseline-tool-calling", "langgraph-react", "full-system"]
        assert second == ["langgraph-react", "full-system", "baseline-tool-calling"]
        assert third == ["full-system", "baseline-tool-calling", "langgraph-react"]

    def test_one_session_expands_to_12_cells_each_once(self):
        units = plan_compression_matrix("sess-x")
        assert len(units) == 12
        assert compression_session_run_count() == 12
        # 4 上下文方式 × 3 Agent,每格 repeat_index=0(每格只运行一次)
        assert len({u.context_variant for u in units}) == 4
        assert len({(u.context_variant, u.agent_mode_id) for u in units}) == 12
        assert all(u.repeat_index == 0 for u in units)
        assert all(u.test_type is TestType.COMPRESSION_CASE for u in units)

    def test_all_sessions_theoretical_count_is_36(self):
        assert compression_all_sessions_run_count(3) == 36

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
