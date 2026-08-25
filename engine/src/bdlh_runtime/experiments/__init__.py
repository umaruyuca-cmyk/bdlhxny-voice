"""两类实验的统一领域模型:压缩用例与对比用例。

三个数量字段全链路分开(页面/接口/记录/工件同名):
- ``test_type``:只有 ``COMPRESSION_CASE``(压缩用例)与 ``COMPARISON_CASE``(对比用例);
- ``repeat_count``:相同实验条件创建多少个独立运行——压缩用例每格固定 1,
  对比用例只能 3 或 5;
- ``max_agent_steps``:单次运行中模型判断与工具结果回传的最大步数,与重复次数无关。

历史兼容说明(弃用口径):data 服务批次表既有列 ``requested_repetitions``
即 ``repeat_count`` 的数据库层旧名;旧接口的 ``runs`` 请求字段与
``AgentLoop.max_tool_calls`` 分别是 ``repeat_count`` / ``max_agent_steps``
的旧口径。公开接口与本包只使用新口径。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum

from bdlh_runtime.engine.loop import (
    STOP_REASON_CANCELLED,
    STOP_REASON_CONTEXT_ERROR,
    STOP_REASON_FINAL_ANSWER,
    STOP_REASON_MAX_AGENT_STEPS,
)


class TestType(StrEnum):
    """实验模块只有两类,页面、接口、数据库与公开工件统一使用该口径。"""

    COMPRESSION_CASE = "COMPRESSION_CASE"
    COMPARISON_CASE = "COMPARISON_CASE"

    # pytest 会把 Test* 类当测试类收集,显式声明不是
    __test__ = False


#: 压缩用例与对比用例共用的三种 Agent 实现稳定编号(目录名,不是页面显示名)。
AGENT_MODE_IDS: tuple[str, ...] = ("baseline-tool-calling", "langgraph-react", "full-system")

#: 压缩用例的四种上下文方式(页面名与 strategy id 一一对应)。
CONTEXT_MODES: tuple[str, ...] = ("full-session", "recent-window", "single-summary", "budgeted-session")

#: 对比用例允许的重复次数;其他数值前后端都必须拒绝。
COMPARISON_REPEAT_COUNTS: tuple[int, ...] = (3, 5)

#: 压缩用例每个实验条件(4×3 矩阵的每格)固定只运行 1 次。
COMPRESSION_REPEAT_COUNT = 1

#: 压缩用例三个操作口径(三个互不自动触发的手动按钮)。
COMPRESSION_SCOPE_CONTEXT_ONLY = "context-only"  # 生成四份上下文,不运行 Agent
COMPRESSION_SCOPE_CURRENT_COMBO = "current-combo"  # 一份工件 × 一种 Agent,运行 1 次
COMPRESSION_SCOPE_FULL_MATRIX = "full-matrix"  # 复用同批四份工件,12 格各 1 次
COMPRESSION_SCOPES: tuple[str, ...] = (
    COMPRESSION_SCOPE_CONTEXT_ONLY,
    COMPRESSION_SCOPE_CURRENT_COMBO,
    COMPRESSION_SCOPE_FULL_MATRIX,
)


class RepeatCountError(ValueError):
    """repeat_count 不符合该实验类型的允许值。"""


def validate_repeat_count(test_type: TestType, repeat_count: int) -> int:
    """服务端权威校验:对比用例只接受 3/5,压缩用例只接受 1。"""
    if not isinstance(repeat_count, int) or isinstance(repeat_count, bool):
        raise RepeatCountError(f"repeat_count 必须是整数,收到 {repeat_count!r}")
    if test_type is TestType.COMPARISON_CASE:
        if repeat_count not in COMPARISON_REPEAT_COUNTS:
            raise RepeatCountError(
                f"对比用例 repeat_count 只能是 {list(COMPARISON_REPEAT_COUNTS)},收到 {repeat_count}"
            )
        return repeat_count
    if test_type is TestType.COMPRESSION_CASE:
        if repeat_count != COMPRESSION_REPEAT_COUNT:
            raise RepeatCountError(
                f"压缩用例每个实验条件固定运行 {COMPRESSION_REPEAT_COUNT} 次,不接受 {repeat_count}"
            )
        return repeat_count
    raise RepeatCountError(f"未知 test_type:{test_type!r}")


def default_max_agent_steps() -> int:
    """单次 Agent 运行最大步数,由服务端配置(MAX_AGENT_STEPS),不进请求。"""
    raw = (os.getenv("MAX_AGENT_STEPS") or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else 8


@dataclass(frozen=True)
class RunUnit:
    """一个待执行的实验单元(= 一次独立运行)。

    对比用例:agent 轮转由 repeat_index 决定;压缩用例:context_variant × agent 固定 12 格。
    """

    unit_id: str
    test_type: TestType
    agent_mode_id: str
    repeat_index: int
    context_variant: str | None = None  # 仅压缩用例
    case_id: str | None = None  # 仅对比用例
    session_id: str | None = None  # 仅压缩用例


def _rotated(modes: tuple[str, ...], offset: int) -> tuple[str, ...]:
    offset %= len(modes)
    return modes[offset:] + modes[:offset]


def plan_comparison_runs(
    case_id: str,
    repeat_count: int,
    *,
    agent_mode_ids: tuple[str, ...] = AGENT_MODE_IDS,
) -> list[RunUnit]:
    """一个对比用例展开为 3×repeat_count 个运行单元,执行顺序按重复编号轮转。

    第 1 组 A→B→C,第 2 组 B→C→A,第 3 组 C→A→B……避免同一种 Agent 总是先运行。
    """
    validate_repeat_count(TestType.COMPARISON_CASE, repeat_count)
    units: list[RunUnit] = []
    for repeat_index in range(repeat_count):
        for mode in _rotated(agent_mode_ids, repeat_index):
            units.append(
                RunUnit(
                    unit_id=f"{case_id}:{mode}:r{repeat_index}",
                    test_type=TestType.COMPARISON_CASE,
                    agent_mode_id=mode,
                    repeat_index=repeat_index,
                    case_id=case_id,
                )
            )
    return units


def plan_compression_matrix(
    session_id: str,
    *,
    context_modes: tuple[str, ...] = CONTEXT_MODES,
    agent_mode_ids: tuple[str, ...] = AGENT_MODE_IDS,
) -> list[RunUnit]:
    """一个压缩 Session 展开为 4×3=12 个实验单元,每格固定 repeat_index=0。"""
    units: list[RunUnit] = []
    for variant in context_modes:
        for mode in agent_mode_ids:
            units.append(
                RunUnit(
                    unit_id=f"{session_id}:{variant}:{mode}",
                    test_type=TestType.COMPRESSION_CASE,
                    agent_mode_id=mode,
                    repeat_index=COMPRESSION_REPEAT_COUNT - 1,
                    context_variant=variant,
                    session_id=session_id,
                )
            )
    return units


def comparison_run_count(repeat_count: int) -> int:
    """运行前准确计算总运行数:一个对比用例 3×3=9 或 3×5=15。"""
    return len(plan_comparison_runs("preview", repeat_count))


def compression_session_run_count() -> int:
    """一个压缩 Session 完整 4×3 = 12 个运行(页面展示口径)。"""
    return len(plan_compression_matrix("preview"))


def compression_all_sessions_run_count(session_count: int = 3) -> int:
    """三个压缩 Session 全部运行理论上为 36;页面只显示数字,不提供默认连跑按钮。"""
    return compression_session_run_count() * session_count


def theoretical_max_model_calls(run_count: int, max_agent_steps: int) -> int:
    """确认窗口展示口径:运行数 × 单次最大步数 = 理论最大模型调用数。"""
    return run_count * max_agent_steps


@dataclass(frozen=True)
class FixedConditions:
    """一个批次内三种 Agent 与全部重复运行共享的固定条件。"""

    model: str
    temperature: float
    max_agent_steps: int
    repeat_count: int
    test_type: TestType
    tool_catalog_version: str
    fixture_set_id: str
    judge_version: str
    extra: dict[str, str] = field(default_factory=dict)


__all__ = [
    "AGENT_MODE_IDS",
    "COMPARISON_REPEAT_COUNTS",
    "COMPRESSION_REPEAT_COUNT",
    "COMPRESSION_SCOPES",
    "COMPRESSION_SCOPE_CONTEXT_ONLY",
    "COMPRESSION_SCOPE_CURRENT_COMBO",
    "COMPRESSION_SCOPE_FULL_MATRIX",
    "CONTEXT_MODES",
    "FixedConditions",
    "RepeatCountError",
    "RunUnit",
    "TestType",
    "comparison_run_count",
    "compression_all_sessions_run_count",
    "compression_session_run_count",
    "default_max_agent_steps",
    "plan_comparison_runs",
    "plan_compression_matrix",
    "theoretical_max_model_calls",
    "validate_repeat_count",
    "STOP_REASON_FINAL_ANSWER",
    "STOP_REASON_MAX_AGENT_STEPS",
    "STOP_REASON_CONTEXT_ERROR",
    "STOP_REASON_CANCELLED",
]
