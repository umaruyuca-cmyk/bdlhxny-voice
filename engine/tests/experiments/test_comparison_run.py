"""对比用例运行测试:9/15 展开、逐次保存、聚合分布、自定义条件与重复拒绝。"""

from __future__ import annotations

import pytest

from bdlh_runtime.experiments import RepeatCountError
from bdlh_runtime.experiments.comparison import (
    ComparisonCase,
    ComparisonCaseError,
    run_comparison_case,
)
from bdlh_runtime.experiments.judge import CallRelationSpec


def _case() -> ComparisonCase:
    return ComparisonCase(
        case_id="cmp-support-01",
        case_version=2,
        title="订单延迟答复",
        message="客户王磊的订单为什么还没到?",
        scene="support",
        allowed_tools=("crm.search_customer", "order.get_status", "policy.search", "knowledge.search"),
        default_visible_tools=("crm.search_customer", "order.get_status", "policy.search", "knowledge.search"),
        fixture_set_id="cmp-fixtures-v1",
        call_relation=CallRelationSpec.from_payload(
            {
                "required_calls": [{"tool": "crm.search_customer"}, {"tool": "order.get_status"}],
                "required_dependencies": [
                    {"from": "crm.search_customer.latest_order_id", "to": "order.get_status.order_id"}
                ],
                "stop_when_facts_available": ["ORD-2049"],
            }
        ),
    )


def _good_runner(case, agent_mode_id, visible_tools, max_agent_steps, *, llm=None):
    return {
        "answer": "订单 ORD-2049 已发货,预计明日送达。",
        "error": None,
        "tool_calls": [
            {"tool": "crm.search_customer", "arguments": {"query": "王磊"},
             "status": "success", "result": {"latest_order_id": "ORD-2049"}},
            {"tool": "order.get_status", "arguments": {"order_id": "ORD-2049"},
             "status": "success", "result": {"status": "已发货"}},
        ],
        "stop_reason": "FINAL_ANSWER",
        "actual_agent_steps": 3,
        "duration_ms": 120,
        "tokens_in": 500,
        "tokens_out": 40,
    }


@pytest.mark.asyncio
async def test_repeat_3_expands_and_saves_every_run():
    result = await run_comparison_case(_case(), 3, agent_runner=_good_runner, max_agent_steps=5)
    assert result.total_runs == 9
    assert len(result.runs) == 9  # 保存每一次运行,不只保存聚合值
    assert result.test_type == "COMPARISON_CASE"
    assert result.repeat_count == 3
    assert result.max_agent_steps == 5
    # 每种 Agent 3 次
    for mode in ("baseline-tool-calling", "langgraph-react", "full-system"):
        assert result.by_agent[mode]["total_runs"] == 3
        assert result.by_agent[mode]["success_count"] == 3


@pytest.mark.asyncio
async def test_repeat_5_expands_to_15_runs():
    result = await run_comparison_case(_case(), 5, agent_runner=_good_runner)
    assert result.total_runs == 15
    assert len(result.runs) == 15


@pytest.mark.asyncio
async def test_other_repeat_counts_rejected():
    for bad in (1, 2, 4, 6):
        with pytest.raises(RepeatCountError):
            await run_comparison_case(_case(), bad, agent_runner=_good_runner)


@pytest.mark.asyncio
async def test_execution_order_rotates_by_repeat_index():
    result = await run_comparison_case(_case(), 3, agent_runner=_good_runner)
    modes = [run.agent_mode_id for run in result.runs]
    assert modes[:3] == ["baseline-tool-calling", "langgraph-react", "full-system"]
    assert modes[3:6] == ["langgraph-react", "full-system", "baseline-tool-calling"]
    assert modes[6:9] == ["full-system", "baseline-tool-calling", "langgraph-react"]


@pytest.mark.asyncio
async def test_aggregation_reports_distribution_and_invalid_separately():
    calls = {"n": 0}

    async def flaky_runner(case, agent_mode_id, visible_tools, max_agent_steps, *, llm=None):
        calls["n"] += 1
        if calls["n"] % 4 == 0:  # 每 4 次出现一次服务错误 → INVALID,不自动补跑
            return {
                "answer": "", "error": "429 rate limited", "tool_calls": [],
                "stop_reason": "", "actual_agent_steps": 0,
            }
        row = _good_runner(case, agent_mode_id, visible_tools, max_agent_steps)
        row["duration_ms"] = 100 + calls["n"] * 10
        return row

    result = await run_comparison_case(_case(), 3, agent_runner=flaky_runner)
    assert result.total_runs == 9
    assert len(result.runs) == 9  # 无效运行也保留,不自动补跑
    assert len(result.invalid_runs) >= 1
    summary = result.by_agent["baseline-tool-calling"]
    assert summary["valid_runs"] + summary["invalid_runs"] == 3
    assert summary["duration_ms_min"] <= summary["duration_ms_median"] <= summary["duration_ms_max"]
    # 离散情况(stdev)在样本 >= 2 时给出
    assert summary["duration_ms_stdev"] is not None or summary["valid_runs"] < 2


@pytest.mark.asyncio
async def test_default_tools_not_custom():
    case = _case()
    result = await run_comparison_case(case, 3, agent_runner=_good_runner)
    assert result.custom_conditions is False
    assert set(result.selected_tool_ids) == set(case.default_visible_tools)


@pytest.mark.asyncio
async def test_adjusted_tool_scope_marks_custom_conditions():
    """用户调整工具范围 → 自定义条件,不进入正式指标(标记持久化在结果中)。"""
    result = await run_comparison_case(
        _case(), 3, selected_tool_ids=("crm.search_customer", "order.get_status"), agent_runner=_good_runner
    )
    assert result.custom_conditions is True
    assert result.selected_tool_ids == ("crm.search_customer", "order.get_status")


@pytest.mark.asyncio
async def test_tool_outside_allowed_scope_rejected():
    with pytest.raises(ComparisonCaseError):
        await run_comparison_case(
            _case(), 3, selected_tool_ids=("crm.search_customer", "mail.send"), agent_runner=_good_runner
        )


@pytest.mark.asyncio
async def test_stop_reason_and_steps_recorded_per_run():
    async def looping_runner(case, agent_mode_id, visible_tools, max_agent_steps, *, llm=None):
        return {
            "answer": "还在查…",
            "error": None,
            "tool_calls": [{"tool": "crm.search_customer", "arguments": {}, "status": "success", "result": {}}],
            "stop_reason": "MAX_AGENT_STEPS",
            "actual_agent_steps": max_agent_steps,
            "duration_ms": 90,
        }

    result = await run_comparison_case(_case(), 3, agent_runner=looping_runner, max_agent_steps=4)
    assert all(run.stop_reason == "MAX_AGENT_STEPS" for run in result.runs)
    assert all(run.actual_agent_steps == 4 for run in result.runs)
    # 步数上限与重复次数无关:repeat_count=3 仍是每运行最多 4 步
    assert result.max_agent_steps == 4 and result.repeat_count == 3


@pytest.mark.asyncio
async def test_cancel_stops_unstarted_units_only():
    started: list[str] = []

    async def runner(case, agent_mode_id, visible_tools, max_agent_steps, *, llm=None):
        started.append(agent_mode_id)
        return _good_runner(case, agent_mode_id, visible_tools, max_agent_steps)

    def should_stop_after_three() -> bool:
        return len(started) >= 3

    result = await run_comparison_case(
        _case(), 3, agent_runner=runner, should_stop=should_stop_after_three
    )
    assert len(result.runs) == 3  # 已产生的运行保留
    assert result.total_runs == 9  # 缺口如实展示,不自动补跑
