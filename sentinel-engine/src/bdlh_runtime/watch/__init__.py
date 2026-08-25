"""看护环（Watch）子系统：事件源、边沿触发与去重、唤醒调度。

设计文档 §4.8 定义了 watch-first 交互模型的契约：

- 规则持久化于 ``watch_rule``，事件流水落 ``watch_event``；
- 事件为**边沿触发**（edge-triggered）：仅在状态穿越阈值时刻产生，水平方向不重复；
- **幂等投递**：``dedupe_key``（规则 × 触发窗口 × 方向）以数据库唯一约束强制；
- 事件产出后经唤醒态上下文组装进入 Agent 引擎（§4.5），解读结果落通知。

依赖纪律（WO-T1-2）：本包仅允许依赖 ``infra/``、``compute/``、``contracts/``
及外部库；不得 import ``cognitive/``、``guardrails/``、``domains/``、``tools/``、
``integrations/`` 等引擎内部件，保持看护环与编排内核解耦。
"""

from __future__ import annotations

from .events import (
    THRESHOLD_DIRECTIONS,
    WATCH_EVENT_SOURCES,
    WATCH_RULE_STATUSES,
    WATCH_RULE_TYPES,
    ThresholdDirection,
    WatchEvent,
    WatchEventSource,
    WatchRule,
    WatchRuleStatus,
    WatchRuleType,
    make_cron_dedupe_key,
    make_price_threshold_dedupe_key,
)

__all__ = [
    "THRESHOLD_DIRECTIONS",
    "WATCH_EVENT_SOURCES",
    "WATCH_RULE_STATUSES",
    "WATCH_RULE_TYPES",
    "ThresholdDirection",
    "WatchEvent",
    "WatchEventSource",
    "WatchRule",
    "WatchRuleStatus",
    "WatchRuleType",
    "make_cron_dedupe_key",
    "make_price_threshold_dedupe_key",
]
