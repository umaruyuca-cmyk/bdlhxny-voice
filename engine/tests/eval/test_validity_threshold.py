"""有效样本门槛与交错运行契约(任务三)。"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from bdlh_runtime.evaluation.ab_eval import (
    ABCase,
    ABReport,
    CaseReport,
    GroupSummary,
    RunJudgment,
    _summarize,
    evaluate_validity_threshold,
    render_markdown,
    run_ab_eval,
)
from bdlh_runtime.evaluation.frozen_observations import FrozenObservations
from bdlh_runtime.tools.catalog import catalog_from_snapshot
from tests.eval.frozen_fixtures import frozen_payload
from tests.eval.test_run_telemetry import RateLimitModel, ScriptedToolModel
from tests.helpers_registry import seeded_snapshot


def _case(case_id: str = "research-01") -> ABCase:
    return ABCase(
        id=case_id,
        category="金融研究",
        message="宁德时代现在什么价",
        scene_tag="market",
        expected_tools=("market.get_realtime_quote",),
        case_version=1,
        variant_id="default",
        snapshot_id=f"{case_id}:fixture-v1",
        snapshot_hash="sha256:snap",
    )


def _orders(run_records: list[Any]) -> list[list[str]]:
    """按 repeat 分组还原三组执行顺序(交错运行的证据)。"""
    by_repeat: dict[int, list[str]] = {}
    for record in run_records:
        by_repeat.setdefault(record.repeat_index, []).append(record.agent_mode)
    return [by_repeat[key] for key in sorted(by_repeat)]


@pytest.mark.asyncio
async def test_interleave_is_deterministic_and_reproducible() -> None:
    kwargs: dict[str, Any] = dict(
        runs_per_case=4,
        llm=ScriptedToolModel(),
        model="glm-4.7-flash",
        with_react=True,
        cases=[_case("research-01"), _case("research-02")],
        catalog=catalog_from_snapshot(seeded_snapshot()),
        frozen=FrozenObservations(frozen_payload()),
        retry_delay_s=0,
        inter_run_delay_s=0,
        interleave_seed=7,
    )
    first = await run_ab_eval(**kwargs)
    second = await run_ab_eval(**kwargs)
    first_order = [record.run_key for record in first.run_records]
    second_order = [record.run_key for record in second.run_records]
    assert first_order == second_order, "同一种子必须可复现执行序"


@pytest.mark.asyncio
async def test_interleave_shuffles_groups_and_rotates_cases() -> None:
    report = await run_ab_eval(
        runs_per_case=4,
        llm=ScriptedToolModel(),
        model="glm-4.7-flash",
        with_react=True,
        cases=[_case("research-01"), _case("research-02")],
        catalog=catalog_from_snapshot(seeded_snapshot()),
        frozen=FrozenObservations(frozen_payload()),
        retry_delay_s=0,
        inter_run_delay_s=0,
        interleave_seed=7,
    )
    orders = _orders(report.run_records)
    assert len(orders) == 4 and all(len(order) == 6 for order in orders)
    canonical = ["baseline-tool-calling", "langgraph-react", "full-system"]
    assert any(order != canonical for order in orders), "组顺序应被洗牌,而非固定三组相邻串行"
    # 题序轮转:repeat 1 的首个运行应是第二条用例(repeat 0 首条是用例一)
    assert report.run_records[0].case_id == "research-01"
    assert report.run_records[6].case_id == "research-02"
    # 报告聚合仍按原题序
    assert [case.case_id for case in report.cases] == ["research-01", "research-02"]


def test_threshold_three_valid_two_invalid_not_met() -> None:
    """验收:3 有效 + 2 无效(429 注入)的批次被判未达门槛。"""
    runs = [RunJudgment(tool_correct=True, validity="VALID", run_key=f"baseline-ok-{index}") for index in range(3)] + [
        RunJudgment(
            error="Error code: 429 - rate limit exceeded",
            validity="INVALID",
            error_category="RATE_LIMITED",
            run_key=f"baseline-429-{index}",
        )
        for index in range(2)
    ]
    summary = _summarize(runs)
    assert summary.total_runs == 5
    assert summary.valid_runs == 3
    assert summary.invalid_runs == 2
    assert summary.invalid_reasons == {"RATE_LIMITED": 2}
    threshold = evaluate_validity_threshold(summary, summary, None, min_valid=5)
    assert threshold["met"] is False
    assert threshold["groups"]["baseline"] == {"required": 5, "valid": 3, "met": False}

    all_valid = [RunJudgment(tool_correct=True, validity="VALID") for _ in range(5)]
    ok_summary = _summarize(all_valid)
    assert evaluate_validity_threshold(ok_summary, ok_summary, ok_summary, min_valid=5)["met"] is True


@pytest.mark.asyncio
async def test_run_ab_eval_threshold_on_mixed_validity(finance_pack) -> None:
    """端到端:基线/ReAct 组全 429、完整模式正常 → 门槛未满足且写入报告。"""

    class Baseline429Model:
        """基线系统提示(裸调用/ReAct 共用)一律 429;完整模式正常。"""

        def __init__(self) -> None:
            self._inner = ScriptedToolModel()

        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            return self

        async def ainvoke(self, messages: Any, **kwargs: Any) -> AIMessage:
            system = str(getattr(messages[0], "content", ""))
            # 仅基线/ReAct 短提示会 429;完整模式 system_base 含「红线」等长文案
            if system.startswith("你是工具型助手。请根据用户问题"):
                raise RuntimeError("Error code: 429 - rate limit exceeded")
            return await self._inner.ainvoke(messages, **kwargs)

    report = await run_ab_eval(
        runs_per_case=1,
        llm=Baseline429Model(),
        model="glm-4.7-flash",
        with_react=True,
        cases=[_case()],
        catalog=catalog_from_snapshot(seeded_snapshot()),
        frozen=FrozenObservations(frozen_payload()),
        retry_delay_s=0,
        inter_run_delay_s=0,
        min_valid_samples=1,
    )
    assert report.baseline.valid_runs == 0
    assert report.baseline.invalid_reasons == {"RATE_LIMITED": 1}
    assert report.treatment.valid_runs == 1
    threshold = report.validity_threshold
    assert threshold["met"] is False
    assert threshold["groups"]["baseline"]["met"] is False
    assert threshold["groups"]["treatment"]["met"] is True


def test_render_no_zero_to_zero_improvement_and_sample_breakdown() -> None:
    """验收:0%→0% 不再渲染为改善;样本三分与门槛结论进报告。"""
    baseline = GroupSummary(
        tool_selection_rate=0.5,
        number_hallucination_rate=0.0,
        total_runs=5,
        valid_runs=5,
        invalid_runs=0,
        invalid_reasons={},
    )
    treatment = GroupSummary(
        tool_selection_rate=0.9,
        number_hallucination_rate=0.0,
        total_runs=5,
        valid_runs=3,
        invalid_runs=2,
        invalid_reasons={"RATE_LIMITED": 2},
    )
    case = CaseReport(case_id="research-01", category="金融研究", message="问句")
    case.baseline_runs = [RunJudgment(tool_correct=True, validity="VALID") for _ in range(5)]
    case.treatment_runs = [RunJudgment(tool_correct=True, validity="VALID") for _ in range(3)] + [
        RunJudgment(error="429", validity="INVALID", error_category="RATE_LIMITED") for _ in range(2)
    ]
    report = ABReport(
        case_count=1,
        runs_per_case=5,
        baseline=baseline,
        treatment=treatment,
        cases=[case],
        validity_threshold=evaluate_validity_threshold(baseline, treatment, None, min_valid=5),
    )
    markdown = render_markdown(report)
    # 0%→0% 的数字幻觉行:变化列必须是占位符,不得渲染 +0pp 改善
    zero_row = next(line for line in markdown.splitlines() if line.startswith("| 数字幻觉率"))
    assert zero_row.endswith("| — |")
    assert "+0pp" not in zero_row
    # 工具选择 50%→90% 仍正常渲染 +40pp
    tool_row = next(line for line in markdown.splitlines() if line.startswith("| 工具选择准确率"))
    assert "+40pp" in tool_row
    # 样本三分 + 门槛结论
    assert "| 完整模式 | 5 | 3 | 2 | RATE_LIMITED×2 |" in markdown
    assert "**有效样本门槛**" in markdown and "未满足" in markdown


@pytest.mark.asyncio
async def test_run_ab_eval_all_invalid_threshold_reported(finance_pack) -> None:
    report = await run_ab_eval(
        runs_per_case=1,
        llm=RateLimitModel(),
        model="glm-4.7-flash",
        with_react=False,
        cases=[_case()],
        catalog=catalog_from_snapshot(seeded_snapshot()),
        frozen=FrozenObservations(frozen_payload()),
        retry_delay_s=0,
        inter_run_delay_s=0,
        min_valid_samples=1,
    )
    assert report.validity_threshold["met"] is False
    markdown = render_markdown(report)
    assert "未满足" in markdown
    assert ToolMessage.__name__  # 引用守卫:消息类型来自 langchain_core
