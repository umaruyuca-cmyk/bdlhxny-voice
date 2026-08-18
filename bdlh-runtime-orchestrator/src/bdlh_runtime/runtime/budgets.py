"""流程运行预算。

预算真源是库表 ``bdlh_runtime_run_budget``（经 RegistrySnapshot 加载）；
代码不再维护按 analysis_type 的六套常量。Agent 只能提出下一步动作，
不能自行延长预算。
"""

from __future__ import annotations

from dataclasses import asdict

from bdlh_runtime.registry import BudgetRecord, RegistrySnapshot


def budget_for_profile(snapshot: RegistrySnapshot, profile: str = "default") -> BudgetRecord:
    """返回指定 profile 的预算；缺失视为配置错误（启动校验已保证 default 存在）。"""
    record = snapshot.budget_for(profile)
    if record is None:
        raise ValueError(f"registry: budget profile {profile!r} is missing")
    return record


def budget_state(record: BudgetRecord) -> dict:
    """写入 state["budget"] 的可序列化形态（消费方沿用既有键名）。"""
    return asdict(record)
