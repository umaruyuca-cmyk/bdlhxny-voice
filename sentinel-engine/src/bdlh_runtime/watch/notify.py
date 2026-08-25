"""看护环通知落库与追问闭环（设计文档 §4.8、§6.1）。

唤醒运行产出结构化事件解读后，经本模块写入通知记录；通知携带 ``run_id``、事件
摘要、严重度，并与 run 结果**唯一绑定**（同一 run 只产生一条通知，§4.9 可靠性）。
通知随后可经 ``POST /notifications/{id}/followup`` 建立携带事件上下文的追问会话。

依赖纪律：通知持久化经端口（``WatchNotificationStore``）注入；``watch/`` 不直接
依赖 Java HTTP 客户端，具体实现（映射到既有 ``runtime.user_notification`` /
Outbox 机制，复用不落新表）由 ``infra/`` 装配时提供。

C-4：演示注入事件（``source=demo_inject``）的 ``source`` 必须透传至通知记录，
保证通知层「演示注入」可辨识。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from .events import WatchEvent

logger = logging.getLogger("bdlh_runtime.watch.notify")


# ── 严重度 ───────────────────────────────────────────────────────────────────

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"
_SEVERITIES: frozenset[str] = frozenset({SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_CRITICAL})


# ── 通知记录 ─────────────────────────────────────────────────────────────────


class WatchNotification(BaseModel):
    """看护环通知记录（与 run 结果唯一绑定）。

    ``run_id`` 为幂等键：同一 run 的解读结果只产生一条通知（§4.9）。
    ``source`` 透传事件来源（含 ``demo_inject``，C-4）。
    """

    notification_id: str
    run_id: str
    user_id: str
    event_id: int | None = None
    event_type: str
    event_summary: str
    severity: str = SEVERITY_INFO
    source: str = "market_poll"  # 透传事件 source；demo_inject 必须保留（C-4）
    title: str = ""
    body: str = ""
    audit_codes: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ── 解读结果视图（由现行编排链路产出，T2 引擎替换后契约不变）──────────────────


class InterpretationResult(BaseModel):
    """唤醒运行的结构化解读结果（§4.8 输出结构）。

    本模型是 notify 与编排链路之间的契约：编排产出 ``InterpretationResult``，
    notify 据此生成通知。T2 引擎替换后该契约保持不变。
    """

    run_id: str
    title: str
    summary: str
    severity: str = SEVERITY_INFO
    audit_codes: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    body: str = ""


# ── 通知持久化端口 ───────────────────────────────────────────────────────────


class WatchNotificationStore(Protocol):
    """通知持久化端口（复用既有 runtime.user_notification / Outbox，不落新表）。"""

    def write(self, notification: WatchNotification) -> WatchNotification:
        """写入通知；``run_id`` 幂等——同一 run 已有通知则返回既有记录。"""
        ...

    def get(self, notification_id: str) -> WatchNotification | None:
        ...

    def list_for_user(self, user_id: str, *, limit: int = 50) -> list[WatchNotification]:
        ...


# ── 通知写入器 ───────────────────────────────────────────────────────────────


class WatchNotificationWriter:
    """解读结果 → 通知写入。

    将 ``InterpretationResult`` + 触发它的 ``WatchEvent`` 组装为
    ``WatchNotification`` 并落库；同一 run 结果只产生一条通知（与 run 唯一绑定）。
    """

    def __init__(self, store: WatchNotificationStore) -> None:
        self._store = store

    def write(
        self,
        *,
        interpretation: InterpretationResult,
        event: WatchEvent,
        user_id: str,
    ) -> WatchNotification:
        if interpretation.severity not in _SEVERITIES:
            raise ValueError(
                f"severity 必须为 {sorted(_SEVERITIES)}，实际：{interpretation.severity!r}"
            )
        notification = WatchNotification(
            notification_id=str(uuid4()),
            run_id=interpretation.run_id,
            user_id=user_id,
            event_id=event.id,
            event_type=event.type,
            event_summary=interpretation.summary,
            severity=interpretation.severity,
            # source 透传：demo_inject 必须保留至通知层（C-4）
            source=event.source,
            title=interpretation.title,
            body=interpretation.body or interpretation.summary,
            audit_codes=list(interpretation.audit_codes),
            evidence_refs=list(interpretation.evidence_refs),
        )
        # store.write 保证 run_id 幂等：重复运行不重复通知（§4.9）
        return self._store.write(notification)


# ── 事件摘要（追问首轮上下文用）──────────────────────────────────────────────


def event_summary_for_followup(event: WatchEvent) -> str:
    """构造追问首轮上下文的事件摘要 chip 文本。

    摘要只含触发事实（时间、类型、关键负载），不含解读结论——追问进入标准对话
    链路后由 Agent 重新组织回答（§4.8 追问闭环）。演示注入事件标注「演示注入」（C-4）。
    """
    payload = event.payload or {}
    demo_tag = "【演示注入】" if event.source == "demo_inject" else ""
    occurred = event.occurred_at.strftime("%m-%d %H:%M")
    if event.type == "price_threshold":
        symbol = payload.get("symbol", "")
        direction = payload.get("direction", "")
        price = payload.get("price")
        pct = payload.get("pct_change")
        detail = f"{symbol} {direction} 价 {price}"
        if pct is not None:
            detail += f"（{pct:+.1f}%）"
        return f"{demo_tag}{occurred} {detail}".strip()
    if event.type in {"daily_briefing", "post_market_review"}:
        day = payload.get("trading_day", "")
        label = "盘前晨报" if event.type == "daily_briefing" else "盘后复盘"
        return f"{demo_tag}{occurred} {label} {day}".strip()
    return f"{demo_tag}{occurred} {event.type}".strip()
