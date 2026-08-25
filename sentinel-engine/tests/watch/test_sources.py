"""看护环事件源单测（WO-T1-8）：交易日判定、边沿触发、去重幂等、失败退避。

覆盖 ``PriceThresholdPoller`` 与 ``CronEventSource``（WO-T1-3 / WO-T1-4）。
全部外部依赖（行情、规则、事件持久化、交易时段）以 Fake 注入。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bdlh_runtime.watch.events import WatchEvent, WatchRule
from bdlh_runtime.watch.sources import (
    CronEventSource,
    DedupeKeyConflict,
    PriceThresholdPoller,
    QuoteSnapshot,
)

# ── Fake 端口 ────────────────────────────────────────────────────────────────


class FakeQuoteProvider:
    def __init__(self, quotes: dict[str, QuoteSnapshot] | None = None, *, raise_exc: Exception | None = None):
        self._quotes = quotes or {}
        self._raise = raise_exc

    async def get_quotes(self, symbols: list[str]) -> dict[str, QuoteSnapshot]:
        if self._raise is not None:
            raise self._raise
        return {s: self._quotes[s] for s in symbols if s in self._quotes}


class FakeRuleStore:
    def __init__(self, rules: list[WatchRule] | None = None):
        self._rules = list(rules or [])
        self.fired: list[tuple[int, datetime]] = []

    def list_active_by_type(self, rule_type: str) -> list[WatchRule]:
        return [r for r in self._rules if r.type == rule_type and r.status == "active"]

    def mark_fired(self, rule_id: int, fired_at: datetime) -> None:
        self.fired.append((rule_id, fired_at))


class FakeEventStore:
    def __init__(self) -> None:
        self._events: list[WatchEvent] = []
        self._keys: set[str] = set()

    def dedupe_key_exists(self, dedupe_key: str) -> bool:
        return dedupe_key in self._keys

    def append(self, event: WatchEvent) -> WatchEvent:
        if event.dedupe_key in self._keys:
            raise DedupeKeyConflict(event.dedupe_key)
        self._keys.add(event.dedupe_key)
        stored = event.model_copy(update={"id": len(self._events) + 1})
        self._events.append(stored)
        return stored

    @property
    def events(self) -> list[WatchEvent]:
        return list(self._events)


class FakeSessionGate:
    def __init__(self, is_open: bool = True):
        self._is_open = is_open

    def is_trading_session(self, at: datetime) -> bool:
        return self._is_open


class FakeCalendar:
    """可控交易日历：声明哪些日期为交易日。"""

    def __init__(self, trading_days: set[str] | None = None):
        self._days = trading_days or set()

    def is_trading_day(self, value):  # noqa: ANN001
        return value.isoformat() in self._days


# ── 固定时钟：2026-08-19（周三）10:00 北京时间，交易时段内 ──────────────────

_TRADING_NOW = datetime(2026, 8, 19, 2, 0, tzinfo=UTC)  # 10:00 北京


def _price_rule(rule_id: int, symbol: str, pct: float, direction: str = "down") -> WatchRule:
    return WatchRule(
        id=rule_id,
        user_id="1",
        type="price_threshold",
        config={"symbol": symbol, "direction": direction, "pct": pct},
        status="active",
    )


def _quote(symbol: str, price: float, prev_close: float = 100.0) -> QuoteSnapshot:
    return QuoteSnapshot(
        symbol=symbol,
        price=price,
        prev_close=prev_close,
        currency="CNY",
        source_time=_TRADING_NOW,
        quality="OK",
    )


# ── PriceThresholdPoller 测试 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_poller_skips_non_trading_session():
    rules = FakeRuleStore([_price_rule(1, "300750", 5.0)])
    poller = PriceThresholdPoller(
        rule_store=rules,
        event_store=FakeEventStore(),
        quote_provider=FakeQuoteProvider({"300750": _quote("300750", 94.0)}),
        session_gate=FakeSessionGate(is_open=False),
        clock=lambda: _TRADING_NOW,
    )
    result = await poller.tick()
    assert result.produced == 0
    assert result.evaluated == 0


@pytest.mark.asyncio
async def test_poller_produces_event_on_pct_crossing_down():
    rules = FakeRuleStore([_price_rule(1, "300750", 5.0, direction="down")])
    events = FakeEventStore()
    poller = PriceThresholdPoller(
        rule_store=rules,
        event_store=events,
        quote_provider=FakeQuoteProvider({"300750": _quote("300750", 94.0)}),  # -6%
        session_gate=FakeSessionGate(True),
        clock=lambda: _TRADING_NOW,
    )
    result = await poller.tick()
    assert result.produced == 1
    assert result.crossed == 1
    assert len(events.events) == 1
    ev = events.events[0]
    assert ev.source == "market_poll"
    assert ev.type == "price_threshold"
    assert ev.payload["direction"] == "down"
    assert ev.dedupe_key == "pt:1:300750:down:2026-08-19"
    assert rules.fired and rules.fired[0][0] == 1


@pytest.mark.asyncio
async def test_poller_no_crossing_no_event():
    rules = FakeRuleStore([_price_rule(1, "300750", 5.0, direction="down")])
    events = FakeEventStore()
    poller = PriceThresholdPoller(
        rule_store=rules,
        event_store=events,
        quote_provider=FakeQuoteProvider({"300750": _quote("300750", 98.0)}),  # -2%
        session_gate=FakeSessionGate(True),
        clock=lambda: _TRADING_NOW,
    )
    result = await poller.tick()
    assert result.produced == 0
    assert result.crossed == 0
    assert events.events == []


@pytest.mark.asyncio
async def test_poller_same_direction_same_day_skipped_via_dedupe():
    rules = FakeRuleStore([_price_rule(1, "300750", 5.0, direction="down")])
    events = FakeEventStore()
    # 预置已存在同方向同日 dedupe_key
    events._keys.add("pt:1:300750:down:2026-08-19")
    poller = PriceThresholdPoller(
        rule_store=rules,
        event_store=events,
        quote_provider=FakeQuoteProvider({"300750": _quote("300750", 94.0)}),
        session_gate=FakeSessionGate(True),
        clock=lambda: _TRADING_NOW,
    )
    result = await poller.tick()
    assert result.produced == 0
    assert result.skipped_already_fired == 1
    assert result.crossed == 1  # 仍判定为穿越，但被去重跳过


@pytest.mark.asyncio
async def test_poller_abs_price_crossing():
    rules = FakeRuleStore([
        WatchRule(id=2, user_id="1", type="price_threshold",
                  config={"symbol": "600519", "direction": "up", "abs_price": 1700.0}, status="active")
    ])
    events = FakeEventStore()
    poller = PriceThresholdPoller(
        rule_store=rules,
        event_store=events,
        quote_provider=FakeQuoteProvider({"600519": _quote("600519", 1750.0)}),
        session_gate=FakeSessionGate(True),
        clock=lambda: _TRADING_NOW,
    )
    result = await poller.tick()
    assert result.produced == 1
    assert events.events[0].payload["direction"] == "up"


@pytest.mark.asyncio
async def test_poller_quote_provider_failure_returns_failed_round():
    rules = FakeRuleStore([_price_rule(1, "300750", 5.0)])
    poller = PriceThresholdPoller(
        rule_store=rules,
        event_store=FakeEventStore(),
        quote_provider=FakeQuoteProvider(raise_exc=RuntimeError("mcp down")),
        session_gate=FakeSessionGate(True),
        clock=lambda: _TRADING_NOW,
    )
    result = await poller.tick()
    assert result.produced == 0
    assert result.failed == 1  # 整轮取价失败，1 条规则计为 failed


@pytest.mark.asyncio
async def test_poller_partial_symbol_failure_does_not_block_others():
    rules = FakeRuleStore([
        _price_rule(1, "300750", 5.0, direction="down"),
        _price_rule(2, "600519", 5.0, direction="down"),
    ])
    events = FakeEventStore()
    # 只有 600519 有行情（跌 6%），300750 缺席
    poller = PriceThresholdPoller(
        rule_store=rules,
        event_store=events,
        quote_provider=FakeQuoteProvider({"600519": _quote("600519", 94.0)}),
        session_gate=FakeSessionGate(True),
        clock=lambda: _TRADING_NOW,
    )
    result = await poller.tick()
    assert result.failed == 1  # 300750 缺席
    assert result.produced == 1  # 600519 仍产出


# ── CronEventSource 测试（WO-T1-4）────────────────────────────────────────────


def _cron_rule(rule_id: int, rule_type: str) -> WatchRule:
    return WatchRule(
        id=rule_id, user_id="1", type=rule_type,
        config={"time": "08:30", "only_trading_day": True}, status="active",
    )


def test_cron_source_trading_day_produces_events():
    cal = FakeCalendar({"2026-08-19"})
    rules = FakeRuleStore([_cron_rule(1, "daily_briefing")])
    events = FakeEventStore()
    source = CronEventSource(
        rule_store=rules, event_store=events, calendar=cal, clock=lambda: _TRADING_NOW,
    )
    produced = source.produce_for("daily_briefing")
    assert len(produced) == 1
    assert produced[0].source == "cron"
    assert produced[0].type == "daily_briefing"
    assert produced[0].payload["trading_day"] == "2026-08-19"
    assert "资讯" not in str(produced[0].payload)  # 负载不含资讯内容


def test_cron_source_non_trading_day_no_events():
    cal = FakeCalendar(set())  # 无交易日
    rules = FakeRuleStore([_cron_rule(1, "daily_briefing")])
    events = FakeEventStore()
    source = CronEventSource(
        rule_store=rules, event_store=events, calendar=cal, clock=lambda: _TRADING_NOW,
    )
    assert source.produce_for("daily_briefing") == []


def test_cron_source_duplicate_skipped():
    cal = FakeCalendar({"2026-08-19"})
    rules = FakeRuleStore([_cron_rule(1, "daily_briefing")])
    events = FakeEventStore()
    source = CronEventSource(
        rule_store=rules, event_store=events, calendar=cal, clock=lambda: _TRADING_NOW,
    )
    first = source.produce_for("daily_briefing")
    second = source.produce_for("daily_briefing")  # 同日重复
    assert len(first) == 1
    assert second == []  # dedupe_key 已存在


def test_cron_source_rejects_unknown_type():
    source = CronEventSource(
        rule_store=FakeRuleStore(), event_store=FakeEventStore(),
        calendar=FakeCalendar({"2026-08-19"}), clock=lambda: _TRADING_NOW,
    )
    with pytest.raises(ValueError):
        source.produce_for("price_threshold")
