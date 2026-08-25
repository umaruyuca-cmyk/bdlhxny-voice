"""看护环事件契约与视图模型（设计文档 §4.8）。

本模块是 watch 子系统的契约真源：

- ``WatchRule``：规则的视图模型，字段对齐 ``runtime.watch_rule`` 表；
- ``WatchEvent``：事件契约，字段对齐 ``runtime.watch_event`` 表；
- ``make_price_threshold_dedupe_key`` / ``make_cron_dedupe_key``：集中产出
  ``dedupe_key``（规则 × 触发窗口 × 方向），作为幂等投递的物理承载。

事件负载（``payload``）只含触发事实，**不含资讯内容**——晨报 / 盘后复盘的
资讯内容由唤醒后的 Agent 运行现取（§4.8：晨报内容不在事件源生成）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

# ── 字面量类型（与 DB CHECK 约束一一对齐）───────────────────────────────────

#: 规则 / 事件类型（对齐 watch_rule.type / watch_event.type CHECK）
WatchRuleType = str
WATCH_RULE_TYPES: frozenset[str] = frozenset(
    {"price_threshold", "daily_briefing", "post_market_review"}
)

#: 事件来源（对齐 watch_event.source CHECK；demo_inject 为 C-4 演示注入标记）
WatchEventSource = str
WATCH_EVENT_SOURCES: frozenset[str] = frozenset(
    {"market_poll", "cron", "demo_inject"}
)

#: 规则状态（对齐 watch_rule.status CHECK）
WatchRuleStatus = str
WATCH_RULE_STATUSES: frozenset[str] = frozenset({"active", "paused"})

#: 价格阈值穿越方向（边沿触发去重的联合判定输入之一）
ThresholdDirection = str
THRESHOLD_DIRECTIONS: frozenset[str] = frozenset({"up", "down"})


# ── 视图模型 ────────────────────────────────────────────────────────────────


class WatchRule(BaseModel):
    """监视规则视图模型（对齐 ``runtime.watch_rule``）。

    ``config`` 为自由 JSONB：

    - ``price_threshold``：``{symbol, direction, pct|abs_price}``
    - ``daily_briefing`` / ``post_market_review``：``{time, only_trading_day}``
    """

    id: int | None = None
    user_id: str
    type: str
    config: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"
    last_fired_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WatchEvent(BaseModel):
    """看护事件契约（对齐 ``runtime.watch_event``）。

    ``dedupe_key`` 由本模块的生成函数集中产出，承载幂等投递（§4.8、D-5）。
    ``source=demo_inject`` 的事件全程携带演示标记（C-4）。
    """

    id: int | None = None
    rule_id: int
    type: str
    source: str
    payload: dict[str, Any] = Field(default_factory=dict)
    dedupe_key: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime | None = None


# ── dedupe_key 生成函数（规则 × 触发窗口 × 方向）─────────────────────────────


def make_price_threshold_dedupe_key(
    rule_id: int,
    symbol: str,
    direction: str,
    window_day: str,
) -> str:
    """价格阈值事件的去重键。

    触发窗口为交易日（``window_day``，ISO 日期串如 ``2026-08-19``）；方向
    ``up``/``down`` 区分同日向上 / 向下穿越——同方向同日只触发一次（边沿触发，
    §4.8）。

    生成键形如 ``pt:{rule_id}:{symbol}:{direction}:{window_day}``，稳定且可读，
    便于运维核查。
    """
    if direction not in THRESHOLD_DIRECTIONS:
        raise ValueError(f"direction 必须为 {sorted(THRESHOLD_DIRECTIONS)}，实际：{direction!r}")
    if not symbol:
        raise ValueError("symbol 不能为空")
    if not window_day:
        raise ValueError("window_day 不能为空")
    return f"pt:{rule_id}:{symbol}:{direction}:{window_day}"


def make_cron_dedupe_key(rule_id: int, window_day: str) -> str:
    """定时类事件（晨报 / 盘后复盘）的去重键。

    触发窗口为交易日（``window_day``）；同规则同日只产出一条事件。
    生成键形如 ``cron:{rule_id}:{window_day}``。
    """
    if not window_day:
        raise ValueError("window_day 不能为空")
    return f"cron:{rule_id}:{window_day}"
