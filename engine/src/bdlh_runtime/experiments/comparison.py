"""对比用例的运行时定义与用例仓库协议。

- 用例定义来自用例库(版本化 case_id + case_version),实验模块只引用不复制;
- 对比用例的运行统一经实验模板(experiments/templates)在原生 Tool Calling
  底座上发起;本模块只保留用例定义、默认可见范围收敛与仓库协议;
- ``repeat_count`` 只接受 3 或 5,前后端一致拒绝其他数值;
- 用户调整工具范围后标记 ``custom_conditions=true``,不进入正式指标。

评判使用调用关系(experiments.judge),不使用唯一 expected_tools 线性数组。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from bdlh_runtime.experiments.judge import CallRelationSpec


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
            raise ComparisonCaseError(f"用例 {self.case_id} 默认可见工具越出允许范围:{sorted(missing)}")


class CaseRepository(Protocol):
    """用例仓库协议:生产为 data 服务客户端,测试用内存实现。"""

    def get_public_case(self, case_id: str) -> ComparisonCase | None: ...


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
            raise ComparisonCaseError(f"工具越出用例允许范围:{sorted(set(unknown))};允许:{list(case.allowed_tools)}")
        selected = requested
    custom = selected != case.default_visible_tools
    return selected, custom
