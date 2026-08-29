"""单次运行执行器(P0-7 13.4):一次调用创建且仅创建一个 Agent 运行。

复用模板批次执行链路(plan_template_batch 以 ``repeat_count=1`` +
单变体子集生成恰好一个运行单元,run_template_batch 执行它),因此
AgentLoop、预算、遥测、有效性判定与批次路径完全一致——限制的是
"一次只启动一个实验样本",不限制 Agent 运行内部的多步模型交互。

批次的"多运行展开"在这里不存在:函数签名不接受 repeat_count,
也不接受变体数组;调用方想要更多样本,必须再次调用。
"""

from __future__ import annotations

import asyncio
from typing import Any

from bdlh_runtime.experiments.series_store import SeriesRecord


class SeriesRunError(RuntimeError):
    """单次运行执行失败(用例缺失、计划展开数异常等)。"""


def execute_series_run(
    series: SeriesRecord,
    variant_id: str,
    *,
    model: str | None = None,
    llm: Any = None,
    model_capability: Any = None,
    max_agent_steps: int | None = None,
) -> dict[str, Any]:
    """执行且仅执行一个运行单元;返回运行 payload(统计模块可直接消费)。

    ``llm=None``(生产)时由执行链按该变体 RunConfig 构建
    独立模型客户端;测试通过 ``llm=`` 显式注入 Fake(方案 9.1/15.7)。
    """
    from bdlh_runtime.experiments.templates import get_template

    template = get_template(series.template_id)
    if "COMPRESSION_CASE" in template.allowed_test_types:
        # 压缩用例:series.case_id 承载 Session 编号;单变体 Agent 运行,
        # 冻结上下文工件复用既有缓存,不重新生成摘要
        from bdlh_runtime.experiments.compression import run_single_compression_method

        return asyncio.run(
            run_single_compression_method(
                series.case_id, variant_id, llm=llm, max_agent_steps=max_agent_steps
            )
        )
    from bdlh_runtime.experiments.public_case_repository import get_case_repository
    from bdlh_runtime.experiments.template_runner import run_template_batch
    from bdlh_runtime.experiments.templates import ROLE_OWNER, plan_template_batch

    case = get_case_repository().get_public_case(series.case_id)
    if case is None:
        raise SeriesRunError(f"未知或非公开对比用例:{series.case_id}")
    plan = plan_template_batch(
        series.template_id,
        repeat_count=1,
        role=ROLE_OWNER,
        advanced=series.advanced or None,
        preset_id=series.preset_id,
        variant_labels=[variant_id],
        model_capability=model_capability,
    )
    if len(plan.runs) != 1:
        raise SeriesRunError(
            f"单次运行计划应恰好展开 1 个运行单元,实际 {len(plan.runs)};拒绝执行"
        )
    report = asyncio.run(
        run_template_batch(
            plan,
            message=case.message,
            visible_tools=case.allowed_tools,
            llm=llm,
            fixtures=list((case.conditions or {}).get("mock_fixtures") or []),
            fixture_version=str(case.fixture_set_id),
        )
    )
    runs = report.get("runs") or []
    if len(runs) != 1:
        raise SeriesRunError(f"单次运行应产出 1 条运行记录,实际 {len(runs)}")
    return runs[0]
