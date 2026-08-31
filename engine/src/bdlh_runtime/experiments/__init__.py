"""两类实验的统一领域模型:压缩用例与对比用例。

三个数量字段全链路分开(页面/接口/记录/工件同名):
- ``test_type``:只有 ``COMPRESSION_CASE``(压缩用例)与 ``COMPARISON_CASE``(对比用例);
- ``repeat_count``:相同实验条件创建多少个独立运行——压缩用例每格固定 1,
  对比用例只能 3 或 5;
- ``max_agent_steps``:单次运行中模型判断与工具结果回传的最大步数,与重复次数无关。

字段口径说明:data 服务批次表既有列 ``requested_repetitions`` 即
``repeat_count`` 的数据库层列名。公开接口与本包只使用 ``repeat_count`` 口径。
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


#: 压缩用例的四种上下文方式(页面名与 strategy id 一一对应)。
CONTEXT_MODES: tuple[str, ...] = ("full-session", "recent-window", "single-summary", "budgeted-session")

#: 新正式运行的统一执行引擎标识(混合路线:原生 Tool Calling AgentLoop)。
NATIVE_AGENT_MODE_ID = "native-tool-calling"

#: 对比用例允许的重复次数;其他数值前后端都必须拒绝。
COMPARISON_REPEAT_COUNTS: tuple[int, ...] = (3, 5)

#: 压缩用例每个实验条件固定只运行 1 次。
COMPRESSION_REPEAT_COUNT = 1

#: 压缩用例操作口径(互不自动触发的手动入口)。
COMPRESSION_SCOPE_CONTEXT_ONLY = "context-only"  # 生成四份上下文,不运行 Agent
COMPRESSION_SCOPE_CURRENT_COMBO = "current-combo"  # 一份工件 × 原生底座,运行 1 次
#: 新默认上下文运行计划(混合路线 D1):4 种上下文 × 1 种固定原生配置。
COMPRESSION_SCOPE_NATIVE_MATRIX = "native-matrix"
COMPRESSION_SCOPES: tuple[str, ...] = (
    COMPRESSION_SCOPE_CONTEXT_ONLY,
    COMPRESSION_SCOPE_CURRENT_COMBO,
    COMPRESSION_SCOPE_NATIVE_MATRIX,
)


class RepeatCountError(ValueError):
    """repeat_count 不符合该实验类型的允许值。"""


def validate_repeat_count(test_type: TestType, repeat_count: int) -> int:
    """服务端权威校验:对比用例只接受 3/5,压缩用例只接受 1。"""
    if not isinstance(repeat_count, int) or isinstance(repeat_count, bool):
        raise RepeatCountError(f"repeat_count 必须是整数,收到 {repeat_count!r}")
    if test_type is TestType.COMPARISON_CASE:
        if repeat_count not in COMPARISON_REPEAT_COUNTS:
            raise RepeatCountError(f"对比用例 repeat_count 只能是 {list(COMPARISON_REPEAT_COUNTS)},收到 {repeat_count}")
        return repeat_count
    if test_type is TestType.COMPRESSION_CASE:
        if repeat_count != COMPRESSION_REPEAT_COUNT:
            raise RepeatCountError(f"压缩用例每个实验条件固定运行 {COMPRESSION_REPEAT_COUNT} 次,不接受 {repeat_count}")
        return repeat_count
    raise RepeatCountError(f"未知 test_type:{test_type!r}")


def default_max_agent_steps() -> int:
    """单次 Agent 运行最大步数,由服务端配置(MAX_AGENT_STEPS),不进请求。"""
    raw = (os.getenv("MAX_AGENT_STEPS") or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else 8


@dataclass(frozen=True)
class RunUnit:
    """一个待执行的实验单元(= 一次独立运行)。

    对比用例:agent 轮转由 repeat_index 决定;压缩用例:context_variant × 原生配置 4 格。
    """

    unit_id: str
    test_type: TestType
    agent_mode_id: str
    repeat_index: int
    context_variant: str | None = None  # 仅压缩用例
    case_id: str | None = None  # 仅对比用例
    session_id: str | None = None  # 仅压缩用例


def plan_native_context_runs(
    session_id: str,
    *,
    context_modes: tuple[str, ...] = CONTEXT_MODES,
) -> list[RunUnit]:
    """新默认上下文运行计划:4 种上下文 × 1 种固定原生 Tool Calling 配置(4×1)。

    唯一自变量是 ``context_strategy``;变体复用同一 Session 版本、当前事件、
    工具目录和 Mock。默认不创建 8 格。
    """
    units: list[RunUnit] = []
    for variant in context_modes:
        units.append(
            RunUnit(
                unit_id=f"{session_id}:{variant}:{NATIVE_AGENT_MODE_ID}",
                test_type=TestType.COMPRESSION_CASE,
                agent_mode_id=NATIVE_AGENT_MODE_ID,
                repeat_index=COMPRESSION_REPEAT_COUNT - 1,
                context_variant=variant,
                session_id=session_id,
            )
        )
    return units


def native_context_run_count() -> int:
    """新默认上下文运行数:4 种上下文 × 1 种原生配置 = 4。"""
    return len(plan_native_context_runs("preview"))


def theoretical_max_model_calls(run_count: int, max_agent_steps: int) -> int:
    """确认窗口展示口径:运行数 × 单次最大步数 = 理论最大模型调用数。"""
    return run_count * max_agent_steps


@dataclass(frozen=True)
class FixedConditions:
    """一个批次内所有实验变体与重复运行共享的固定条件。"""

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
    "COMPARISON_REPEAT_COUNTS",
    "COMPRESSION_REPEAT_COUNT",
    "COMPRESSION_SCOPES",
    "COMPRESSION_SCOPE_CONTEXT_ONLY",
    "COMPRESSION_SCOPE_CURRENT_COMBO",
    "COMPRESSION_SCOPE_NATIVE_MATRIX",
    "CONTEXT_MODES",
    "FixedConditions",
    "NATIVE_AGENT_MODE_ID",
    "RepeatCountError",
    "RunUnit",
    "TestType",
    "default_max_agent_steps",
    "native_context_run_count",
    "plan_native_context_runs",
    "theoretical_max_model_calls",
    "validate_repeat_count",
    "STOP_REASON_FINAL_ANSWER",
    "STOP_REASON_MAX_AGENT_STEPS",
    "STOP_REASON_CONTEXT_ERROR",
    "STOP_REASON_CANCELLED",
]
