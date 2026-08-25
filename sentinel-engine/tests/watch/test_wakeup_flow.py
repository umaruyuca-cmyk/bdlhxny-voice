"""唤醒→通知→followup 闭环单测（WO-T1-8）。

覆盖 ``WakeupAssembler``（WO-T1-5）、``WatchNotificationWriter``（WO-T1-6）、
``create_followup_session``。数据面与记忆以 Fake 注入；LLM 不参与（本测试只到
通知落库与 followup 建会话，解读由 InterpretationResult 直接给定）。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bdlh_runtime.infra.chat_sessions import InMemoryChatSessionStore, create_followup_session
from bdlh_runtime.watch.events import WatchEvent, make_price_threshold_dedupe_key
from bdlh_runtime.watch.notify import (
    InterpretationResult,
    WatchNotification,
    WatchNotificationWriter,
    event_summary_for_followup,
)
from bdlh_runtime.watch.wakeup import WakeupAssembler

_NOW = datetime(2026, 8, 19, 6, 32, tzinfo=UTC)


def _demo_event() -> WatchEvent:
    return WatchEvent(
        rule_id=1,
        type="price_threshold",
        source="demo_inject",
        payload={"symbol": "300750", "direction": "down", "price": 171.0, "prev_close": 180.0, "pct_change": -5.0},
        dedupe_key=make_price_threshold_dedupe_key(1, "300750", "down", "2026-08-19"),
        occurred_at=_NOW,
    )


# ── WakeupAssembler ──────────────────────────────────────────────────────────


class _FakePortfolioProvider:
    def __init__(self, snapshot: dict | None = None, *, raise_exc: Exception | None = None):
        self._snapshot = snapshot
        self._raise = raise_exc

    async def get_snapshot(self, user_id: str):
        if self._raise:
            raise self._raise
        return self._snapshot


class _FakeRiskProfileProvider:
    def __init__(self, profile: dict | None = None, *, raise_exc: Exception | None = None):
        self._profile = profile
        self._raise = raise_exc

    async def get_profile(self, user_id: str):
        if self._raise:
            raise self._raise
        return self._profile


class _FakeMemoryStore:
    """记忆 store：search_with_status 返回可控结果。"""

    def __init__(self, records=None, *, degraded: bool = False, raise_exc: Exception | None = None):
        self._records = list(records or [])
        self._degraded = degraded
        self._raise = raise_exc

    async def search_with_status(self, query, user_id, limit=5):
        if self._raise:
            raise self._raise
        return self._records, self._degraded


@pytest.mark.asyncio
async def test_wakeup_pack_fields_complete():
    asm = WakeupAssembler(
        portfolio_provider=_FakePortfolioProvider({"positions": [{"code": "300750"}]}),
        risk_profile_provider=_FakeRiskProfileProvider({"risk_tolerance": "moderate"}),
        memory_store=_FakeMemoryStore(records=[{"id": "m1", "content": "两年内换房"}]),
    )
    pack = await asm.assemble(_demo_event(), "1")
    assert pack.event.type == "price_threshold"
    assert pack.user_id == "1"
    assert pack.system_prompt_ref == "prompts/scene_wakeup.md"
    assert "事件解读" in pack.system_prompt  # 提示已加载
    assert pack.portfolio_snapshot == {"positions": [{"code": "300750"}]}
    assert pack.risk_profile == {"risk_tolerance": "moderate"}
    assert len(pack.memory_records) == 1
    assert not pack.memory_degraded
    assert not pack.portfolio_degraded


@pytest.mark.asyncio
async def test_wakeup_memory_degraded_not_blocking():
    asm = WakeupAssembler(
        portfolio_provider=_FakePortfolioProvider({"positions": []}),
        risk_profile_provider=_FakeRiskProfileProvider({"risk_tolerance": "moderate"}),
        memory_store=_FakeMemoryStore(raise_exc=RuntimeError("memory down")),
    )
    pack = await asm.assemble(_demo_event(), "1")
    # 记忆失败：标 degraded，但不阻断——唤醒包仍产出
    assert pack.memory_degraded
    assert pack.memory_limitation == "semantic_memory_degraded"
    assert pack.memory_records == []
    assert pack.portfolio_snapshot is not None  # 持仓未受影响


@pytest.mark.asyncio
async def test_wakeup_portfolio_degraded_not_blocking():
    asm = WakeupAssembler(
        portfolio_provider=_FakePortfolioProvider(raise_exc=RuntimeError("java down")),
        risk_profile_provider=_FakeRiskProfileProvider({"risk_tolerance": "moderate"}),
        memory_store=None,  # 无记忆配置：recall 返回 degraded=False
    )
    pack = await asm.assemble(_demo_event(), "1")
    assert pack.portfolio_degraded
    assert pack.portfolio_snapshot is None
    assert not pack.memory_degraded  # store=None 视为未配置，非降级


# ── WatchNotificationWriter（WO-T1-6）────────────────────────────────────────


class _InMemoryNotificationStore:
    def __init__(self):
        self._by_id: dict[str, WatchNotification] = {}
        self._by_run: dict[str, WatchNotification] = {}

    def write(self, notification: WatchNotification) -> WatchNotification:
        existing = self._by_run.get(notification.run_id)
        if existing is not None:
            return existing  # run_id 幂等：同一 run 只一条通知
        self._by_id[notification.notification_id] = notification
        self._by_run[notification.run_id] = notification
        return notification

    def get(self, notification_id: str) -> WatchNotification | None:
        return self._by_id.get(notification_id)

    def list_for_user(self, user_id: str, *, limit: int = 50):
        return [n for n in self._by_id.values() if n.user_id == user_id][:limit]


def _interpretation(run_id: str = "run-1") -> InterpretationResult:
    return InterpretationResult(
        run_id=run_id,
        title="宁德时代 -5.2%【演示注入】",
        summary="占仓 18%，浮盈 +24%→+11%，画像稳健型容忍带内",
        severity="warning",
        audit_codes=["RO-OK", "DEMO"],
        evidence_refs=["[1] 行情快照", "[2] 持仓"],
    )


def test_notification_write_binds_run_and_passes_demo_source():
    store = _InMemoryNotificationStore()
    writer = WatchNotificationWriter(store)
    n = writer.write(interpretation=_interpretation(), event=_demo_event(), user_id="1")
    assert n.run_id == "run-1"
    assert n.source == "demo_inject"  # C-4：demo_inject 透传至通知层
    assert n.severity == "warning"
    assert n.event_type == "price_threshold"
    assert "演示注入" in n.title
    assert "DEMO" in n.audit_codes


def test_notification_idempotent_on_run_id():
    store = _InMemoryNotificationStore()
    writer = WatchNotificationWriter(store)
    first = writer.write(interpretation=_interpretation("run-x"), event=_demo_event(), user_id="1")
    # 同一 run 重复写入：返回既有通知，不新增
    second = writer.write(interpretation=_interpretation("run-x"), event=_demo_event(), user_id="1")
    assert first.notification_id == second.notification_id
    assert len(store.list_for_user("1")) == 1


# ── followup 闭环（WO-T1-6）──────────────────────────────────────────────────


def test_followup_session_injects_event_context():
    store = InMemoryChatSessionStore()
    summary = event_summary_for_followup(_demo_event())
    assert "演示注入" in summary  # C-4：chip 含演示标记
    session = create_followup_session(store, user_id="1", event_summary=summary)
    assert session.user_id == "1"
    reloaded = store.get(session.session_id, "1")
    assert reloaded is not None
    # 首轮上下文含事件摘要（system 消息）
    assert any(m.role == "system" and summary in m.content for m in reloaded.messages)


def test_followup_summary_for_market_poll_has_no_demo_tag():
    ev = _demo_event().model_copy(update={"source": "market_poll"})
    summary = event_summary_for_followup(ev)
    assert "演示注入" not in summary
