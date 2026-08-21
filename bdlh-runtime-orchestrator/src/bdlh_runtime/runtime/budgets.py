"""流程运行预算（配置层单一真源；非 Registry 表）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from bdlh_runtime.registry.defaults import (
    DEFAULT_REACT_ROUND_LIMIT,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_SUBGRAPH_TIMEOUT_SECONDS,
    DEFAULT_TOOL_CALL_LIMIT,
)


@dataclass(frozen=True)
class BudgetRecord:
    profile: str
    react_round_limit: int
    tool_call_limit: int
    subgraph_timeout_seconds: int
    request_timeout_seconds: int


def default_budget(*, profile: str = "default") -> BudgetRecord:
    return BudgetRecord(
        profile=profile,
        react_round_limit=DEFAULT_REACT_ROUND_LIMIT,
        tool_call_limit=DEFAULT_TOOL_CALL_LIMIT,
        subgraph_timeout_seconds=DEFAULT_SUBGRAPH_TIMEOUT_SECONDS,
        request_timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS,
    )


def budget_from_settings(settings: object, *, profile: str = "default") -> BudgetRecord:
    return BudgetRecord(
        profile=profile,
        react_round_limit=int(getattr(settings, "default_react_round_limit", DEFAULT_REACT_ROUND_LIMIT)),
        tool_call_limit=int(getattr(settings, "default_tool_call_limit", DEFAULT_TOOL_CALL_LIMIT)),
        subgraph_timeout_seconds=int(
            getattr(settings, "default_subgraph_timeout_seconds", DEFAULT_SUBGRAPH_TIMEOUT_SECONDS)
        ),
        request_timeout_seconds=int(
            getattr(settings, "default_request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT_SECONDS)
        ),
    )


def budget_for_profile(snapshot=None, profile: str = "default") -> BudgetRecord:
    """兼容旧签名；预算不再来自 Registry 快照。"""
    del snapshot
    return default_budget(profile=profile)


def budget_state(record: BudgetRecord) -> dict:
    """写入 state["budget"] 的可序列化形态。"""
    return asdict(record)
