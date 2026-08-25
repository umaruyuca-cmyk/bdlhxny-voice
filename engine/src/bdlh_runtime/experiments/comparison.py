"""对比用例运行:一个固定用例 × 三种 Agent × 重复 3 或 5 次。

规则(与设计文档一致):
- 用例定义来自用例库(版本化 case_id + case_version),实验模块只引用不复制;
- 一次对比任务自动包含全部三种 Agent 实现(固定 Agent 目录),用户不能只挑一个;
- ``repeat_count`` 只接受 3 或 5,前端显示、后端拒绝其他数值;
- 同一批次固定问题、工具定义及顺序、Mock 版本、模型条件、``max_agent_steps``、
  权限和评判版本;执行顺序按重复编号轮换,不改变输入条件;
- 保存每一次运行(不只聚合值):成功次数、最小/中位数/最大值与离散情况,
  无效运行单独显示,不自动补跑;
- 用户调整工具范围后标记 ``custom_conditions=true``,不进入正式指标。

评判使用调用关系(experiments.judge),不使用唯一 expected_tools 线性数组。
"""

from __future__ import annotations

import inspect
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from bdlh_runtime.experiments import (
    AGENT_MODE_IDS,
    RunUnit,
    TestType,
    plan_comparison_runs,
    validate_repeat_count,
)
from bdlh_runtime.experiments.judge import (
    CallRelationSpec,
    JudgedCall,
    RelationJudgment,
    judge_run,
)


class ComparisonCaseError(ValueError):
    """对比用例定义缺失或不合法。"""


@dataclass(frozen=True)
class ComparisonCase:
    """一个公开对比用例的运行时定义(评判配置仅供调度器与评判器读取)。"""

    case_id: str
    case_version: int
    title: str
    message: str
    scene: str
    #: 标准可见工具范围(目标工具 + 相似干扰工具 + 少量无关工具,顺序固定)
    allowed_tools: tuple[str, ...]
    #: 默认勾选的标准工具集合(必须是与 allowed_tools 的一致子集)
    default_visible_tools: tuple[str, ...]
    #: 冻结 Mock 数据版本;同批次内不随机变化
    fixture_set_id: str
    #: 内部评判配置(调用关系);不进入模型输入、工具描述、匿名接口或公开 JSON
    call_relation: CallRelationSpec
    #: 允许的重复次数之外的固定条件快照
    conditions: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.allowed_tools:
            raise ComparisonCaseError(f"用例 {self.case_id} 未定义标准工具范围")
        missing = set(self.default_visible_tools) - set(self.allowed_tools)
        if missing:
            raise ComparisonCaseError(
                f"用例 {self.case_id} 默认可见工具越出允许范围:{sorted(missing)}"
            )


class CaseRepository(Protocol):
    """用例仓库协议:生产为 data 服务客户端,测试用内存实现。"""

    def get_public_case(self, case_id: str) -> ComparisonCase | None: ...


@dataclass
class ComparisonUnitRun:
    """一次独立运行的完整记录(保存每一次,不只保存聚合值)。"""

    unit_id: str
    agent_mode_id: str
    repeat_index: int
    answer: str
    tool_calls: list[dict[str, Any]]
    judgment: dict[str, Any]
    task_success: bool
    validity: str  # VALID | INVALID
    error: str | None
    duration_ms: int
    stop_reason: str
    actual_agent_steps: int
    tokens_in: int
    tokens_out: int


#: 单元执行器协议:async (case, agent_mode_id, visible_tools, max_agent_steps) -> raw dict
AgentRunner = Callable[..., Any]


async def _default_agent_runner(
    case: ComparisonCase,
    agent_mode_id: str,
    visible_tools: tuple[str, ...],
    max_agent_steps: int,
    *,
    llm: Any = None,
) -> dict[str, Any]:
    """生产执行器:三种实现共用冻结 Mock 工具与固定输入条件。"""
    from bdlh_runtime.evaluation.comparison_agent import run_comparison_agent

    return await run_comparison_agent(
        case=case,
        agent_mode_id=agent_mode_id,
        visible_tools=visible_tools,
        max_agent_steps=max_agent_steps,
        llm=llm,
    )


@dataclass
class ComparisonRunResult:
    """一个对比任务的完整结果:逐次运行 + 按 Agent 聚合。"""

    case_id: str
    case_version: int
    test_type: str
    repeat_count: int
    max_agent_steps: int
    total_runs: int
    runs: list[ComparisonUnitRun]
    by_agent: dict[str, dict[str, Any]]
    invalid_runs: list[dict[str, Any]]
    custom_conditions: bool
    selected_tool_ids: tuple[str, ...]
    fixture_set_id: str
    execution_order: list[str]


def resolve_visible_tools(
    case: ComparisonCase,
    selected_tool_ids: tuple[str, ...] | list[str] | None,
) -> tuple[tuple[str, ...], bool]:
    """三层工具范围收敛 + 自定义条件判定。

    返回 (本次可见工具, custom_conditions)。服务端不信任前端标记,
    依据「与默认范围是否完全一致」重新计算 custom_conditions。
    """
    if selected_tool_ids is None:
        selected = case.default_visible_tools
    else:
        requested = tuple(dict.fromkeys(str(name) for name in selected_tool_ids))
        unknown = [name for name in requested if name not in set(case.allowed_tools)]
        if unknown:
            raise ComparisonCaseError(
                f"工具越出用例允许范围:{sorted(set(unknown))};允许:{list(case.allowed_tools)}"
            )
        selected = requested
    custom = selected != case.default_visible_tools
    return selected, custom


async def run_comparison_case(
    case: ComparisonCase,
    repeat_count: int,
    *,
    selected_tool_ids: tuple[str, ...] | list[str] | None = None,
    max_agent_steps: int = 8,
    agent_runner: AgentRunner | None = None,
    should_stop: Callable[[], bool] | None = None,
    inter_run_delay_s: float = 0.0,
    llm: Any = None,
) -> ComparisonRunResult:
    """执行一个对比任务:3 种 Agent × repeat_count,共 9 或 15 个运行。"""
    validate_repeat_count(TestType.COMPARISON_CASE, repeat_count)
    visible_tools, custom_conditions = resolve_visible_tools(case, selected_tool_ids)
    units: list[RunUnit] = plan_comparison_runs(case.case_id, repeat_count)
    runner = agent_runner or _default_agent_runner

    runs: list[ComparisonUnitRun] = []
    invalid: list[dict[str, Any]] = []
    for unit in units:
        if should_stop is not None and should_stop():
            break  # 取消只阻止尚未开始的单元,已产生的运行与费用保留;不自动补跑
        started = time.perf_counter()
        raw = runner(case, unit.agent_mode_id, visible_tools, max_agent_steps, llm=llm)
        if inspect.isawaitable(raw):  # 支持同步/异步两种执行器形态
            raw = await raw
        judged_calls = [
            JudgedCall(
                seq=index + 1,
                tool=str(row.get("tool") or ""),
                arguments=dict(row.get("arguments") or {}),
                status=str(row.get("status") or "success"),
                result=row.get("result"),
            )
            for index, row in enumerate(raw.get("tool_calls") or [])
        ]
        judgment: RelationJudgment = judge_run(
            case.call_relation,
            judged_calls,
            str(raw.get("answer") or ""),
            visible_tools=visible_tools,
        )
        error = raw.get("error")
        validity = "INVALID" if error else "VALID"
        from dataclasses import asdict

        record = ComparisonUnitRun(
            unit_id=unit.unit_id,
            agent_mode_id=unit.agent_mode_id,
            repeat_index=unit.repeat_index,
            answer=str(raw.get("answer") or ""),
            tool_calls=list(raw.get("tool_calls") or []),
            judgment=asdict(judgment),
            task_success=bool(judgment.task_success and not error),
            validity=validity,
            error=error,
            duration_ms=int(raw.get("duration_ms") or round((time.perf_counter() - started) * 1000)),
            stop_reason=str(raw.get("stop_reason") or ""),
            actual_agent_steps=int(raw.get("actual_agent_steps") or 0),
            tokens_in=int(raw.get("tokens_in") or 0),
            tokens_out=int(raw.get("tokens_out") or 0),
        )
        runs.append(record)
        if validity == "INVALID":
            invalid.append({"unit_id": record.unit_id, "error": record.error})
        if inter_run_delay_s:
            import asyncio

            await asyncio.sleep(inter_run_delay_s)

    return ComparisonRunResult(
        case_id=case.case_id,
        case_version=case.case_version,
        test_type=TestType.COMPARISON_CASE.value,
        repeat_count=repeat_count,
        max_agent_steps=max_agent_steps,
        total_runs=len(units),
        runs=runs,
        by_agent=_aggregate_by_agent(runs),
        invalid_runs=invalid,
        custom_conditions=custom_conditions,
        selected_tool_ids=visible_tools,
        fixture_set_id=case.fixture_set_id,
        execution_order=[unit.unit_id for unit in units],
    )


def _aggregate_by_agent(runs: list[ComparisonUnitRun]) -> dict[str, dict[str, Any]]:
    """三种 Agent 的重复结果分布:成功次数、最小/中位数/最大值与离散情况。"""
    grouped: dict[str, list[ComparisonUnitRun]] = {}
    for run in runs:
        grouped.setdefault(run.agent_mode_id, []).append(run)
    summary: dict[str, dict[str, Any]] = {}
    for mode in AGENT_MODE_IDS:
        rows = grouped.get(mode, [])
        valid = [row for row in rows if row.validity == "VALID"]
        durations = sorted(row.duration_ms for row in valid)
        steps = sorted(row.actual_agent_steps for row in valid)
        summary[mode] = {
            "total_runs": len(rows),
            "valid_runs": len(valid),
            "invalid_runs": len(rows) - len(valid),
            "success_count": sum(1 for row in valid if row.task_success),
            "duration_ms_min": durations[0] if durations else None,
            "duration_ms_median": statistics.median(durations) if durations else None,
            "duration_ms_max": durations[-1] if durations else None,
            "duration_ms_stdev": round(statistics.stdev(durations), 2) if len(durations) >= 2 else None,
            "agent_steps_min": steps[0] if steps else None,
            "agent_steps_max": steps[-1] if steps else None,
            "missing_runs": 0,  # 取消造成的缺口由 total_runs - 实际运行数体现
        }
    return summary
