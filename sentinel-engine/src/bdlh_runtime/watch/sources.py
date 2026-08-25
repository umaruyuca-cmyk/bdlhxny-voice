"""看护环事件源（设计文档 §4.8）。

本模块实现两类事件源：

- **价格阈值事件源**（``PriceThresholdPoller``）：交易时段内轮询活跃
  ``price_threshold`` 规则，按标的聚合批量取价，边沿触发判定后产出
  ``WatchEvent`` 落库；数据源失败指数退避，不中断轮询循环。
- **定时事件源**（``CronEventSource``）：``daily_briefing`` / ``post_market_review``
  两类 cron 规则，仅交易日产出事件（WO-T1-4）。

依赖纪律（WO-T1-2）：仅依赖 ``compute/``（交易日历）、``contracts/`` 与本包
契约；行情取价、规则与事件持久化均经端口（Protocol）注入，具体实现由
``infra/`` 装配时提供，保证事件源可单测（Fake 注入）。

边沿触发（§4.8、D-5）：仅在状态穿越阈值的时刻产生事件；同方向同日不重复
触发——由 ``watch_rule.last_fired_at`` 与当日已存事件的 ``dedupe_key`` 联合
判定，``dedupe_key`` 唯一约束为最终物理保证。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, timezone
from typing import Protocol

from pydantic import BaseModel

from bdlh_runtime.compute.trading_calendar import AShareTradingCalendar, create_trading_calendar

from .events import (
    THRESHOLD_DIRECTIONS,
    WatchEvent,
    WatchRule,
    make_cron_dedupe_key,
    make_price_threshold_dedupe_key,
)

logger = logging.getLogger("bdlh_runtime.watch.sources")

# 北京时间（UTC+8）：A 股交易时段与交易日窗口按此时区判定
_CST = timezone(timedelta(hours=8))


# ── 行情快照 ────────────────────────────────────────────────────────────────


class QuoteSnapshot(BaseModel):
    """标准化行情快照（事件源消费的最小行情契约）。

    ``prev_close`` 为 pct 阈值判定的参考价（前收）；``abs_price`` 阈值判定
    不需要它，但取价时一并返回以便统一处理。
    """

    symbol: str
    price: float
    prev_close: float | None = None
    currency: str = "CNY"
    source_time: datetime
    quality: str = "OK"  # OK / STALE / INVALID


class QuoteProvider(Protocol):
    """行情取价端口（批量）。实现可包装 MCP ``market.get_realtime_quote``。"""

    async def get_quotes(self, symbols: list[str]) -> dict[str, QuoteSnapshot]:
        """返回 symbol → QuoteSnapshot；取价失败的标的不出现在结果中。"""
        ...


# ── 规则 / 事件 持久化端口 ────────────────────────────────────────────────────


class WatchRuleStore(Protocol):
    """监视规则持久化端口（读活跃规则、回填触发时间）。"""

    def list_active_by_type(self, rule_type: str) -> list[WatchRule]:
        """返回指定类型下 status=active 的规则。"""
        ...

    def mark_fired(self, rule_id: int, fired_at: datetime) -> None:
        """回填 watch_rule.last_fired_at（边沿触发去重的联合判定输入）。"""
        ...


class WatchEventStore(Protocol):
    """事件流水持久化端口。"""

    def dedupe_key_exists(self, dedupe_key: str) -> bool:
        """该 dedupe_key 是否已存在（幂等预检，最终保证仍靠唯一约束）。"""
        ...

    def append(self, event: WatchEvent) -> WatchEvent:
        """追加事件；dedupe_key 冲突时抛 ``DedupeKeyConflict``（由调用方吞并）。"""
        ...


class DedupeKeyConflict(Exception):
    """dedupe_key 唯一约束冲突——事件已存在，调用方应视为幂等成功。"""


# ── 交易时段门 ───────────────────────────────────────────────────────────────


class TradingSessionGate(Protocol):
    """交易时段判定端口。轮询器仅在交易时段运行（§4.8 轮询纪律）。"""

    def is_trading_session(self, at: datetime) -> bool:
        ...


# A 股交易时段（北京时间）：9:30–11:30、13:00–15:00
_ASHARE_MORNING_OPEN = time(9, 30)
_ASHARE_MORNING_CLOSE = time(11, 30)
_ASHARE_AFTERNOON_OPEN = time(13, 0)
_ASHARE_AFTERNOON_CLOSE = time(15, 0)


class AShareTradingSessionGate:
    """A 股交易时段门：交易日（exchange_calendars XSHG）+ 当日交易时段。"""

    def __init__(self, calendar: AShareTradingCalendar | None = None) -> None:
        self._calendar = calendar or create_trading_calendar()

    def is_trading_session(self, at: datetime) -> bool:
        # 统一按北京时间（UTC+8）判定时段；输入可能是任意时区aware datetime。
        beijing = at.astimezone(_CST)
        if not self._calendar.is_trading_day(beijing.date()):
            return False
        local_time = beijing.time().replace(microsecond=0)
        return (
            _ASHARE_MORNING_OPEN <= local_time <= _ASHARE_MORNING_CLOSE
            or _ASHARE_AFTERNOON_OPEN <= local_time <= _ASHARE_AFTERNOON_CLOSE
        )


# ── 价格阈值事件源 ───────────────────────────────────────────────────────────


def _today_key(at: datetime) -> str:
    """事件触发窗口 = 交易日（按北京时间取日期串，ISO 格式）。"""
    beijing = at.astimezone(_CST)
    return beijing.date().isoformat()


def _evaluate_crossing(rule: WatchRule, quote: QuoteSnapshot) -> str | None:
    """判定规则是否穿越阈值；返回方向 ``up``/``down`` 或 None（未穿越）。

    config 约定：
    - ``direction``：``up`` / ``down``（规则只盯单方向穿越）；
    - ``pct``：涨跌幅阈值（百分点，如 5 表示 5%）；需 ``prev_close``；
    - ``abs_price``：绝对价格阈值。
    """
    config = rule.config or {}
    direction = config.get("direction")
    if direction not in THRESHOLD_DIRECTIONS:
        return None  # 配置非法：静默跳过，不污染事件流

    if "pct" in config:
        prev_close = quote.prev_close
        if not prev_close or prev_close <= 0:
            return None  # 无参考价：无法判定 pct 穿越
        pct_threshold = float(config["pct"])
        pct_change = (quote.price - prev_close) / prev_close * 100.0
        if direction == "down" and pct_change <= -pct_threshold:
            return "down"
        if direction == "up" and pct_change >= pct_threshold:
            return "up"
        return None

    if "abs_price" in config:
        abs_threshold = float(config["abs_price"])
        if direction == "down" and quote.price <= abs_threshold:
            return "down"
        if direction == "up" and quote.price >= abs_threshold:
            return "up"
        return None

    return None


@dataclass
class PriceThresholdTickResult:
    """单次轮询结果摘要（审计与测试断言用）。"""

    evaluated: int = 0
    crossed: int = 0
    produced: int = 0
    skipped_already_fired: int = 0
    failed: int = 0


class PriceThresholdPoller:
    """价格阈值事件源。

    单次 ``tick`` 流程：
    1. 交易时段判定——非交易时段直接返回（不发起请求，配额控制）；
    2. 读活跃 ``price_threshold`` 规则，按标的聚合；
    3. 批量取价（失败标的缺席结果，记日志不中断）；
    4. 逐规则边沿触发判定（dedupe_key 预检 + 穿越检测）；
    5. 穿越则产出 ``WatchEvent``（source=market_poll）落库并回填 last_fired_at。
    """

    SOURCE = "market_poll"

    def __init__(
        self,
        *,
        rule_store: WatchRuleStore,
        event_store: WatchEventStore,
        quote_provider: QuoteProvider,
        session_gate: TradingSessionGate | None = None,
        clock: Callable[[], datetime] | None = None,  # type: ignore[type-arg]
    ) -> None:
        self._rules = rule_store
        self._events = event_store
        self._quotes = quote_provider
        self._session_gate = session_gate or AShareTradingSessionGate()
        self._now = clock or (lambda: datetime.now(UTC))

    async def tick(self) -> PriceThresholdTickResult:
        now = self._now()
        if not self._session_gate.is_trading_session(now):
            logger.debug("price-threshold tick: non-trading session, skip")
            return PriceThresholdTickResult()

        rules = self._rules.list_active_by_type("price_threshold")
        if not rules:
            return PriceThresholdTickResult()

        symbols = sorted({r.config.get("symbol") for r in rules if r.config.get("symbol")})
        if not symbols:
            return PriceThresholdTickResult()

        try:
            quotes = await self._quotes.get_quotes(symbols)
        except Exception as exc:  # 数据源整体失败：记日志，本轮放弃（退避由循环层处理）
            logger.warning("price-threshold tick: quote provider failed: %s", exc)
            return PriceThresholdTickResult(failed=len(rules))

        window_day = _today_key(now)
        result = PriceThresholdTickResult()
        for rule in rules:
            symbol = rule.config.get("symbol")
            quote = quotes.get(symbol) if symbol else None
            if quote is None or quote.quality in {"STALE", "INVALID"} or quote.price <= 0:
                result.failed += 1
                continue
            result.evaluated += 1

            crossing = _evaluate_crossing(rule, quote)
            if crossing is None:
                continue
            result.crossed += 1  # 检测到穿越（不论是否被去重）

            dedupe_key = make_price_threshold_dedupe_key(
                rule_id=rule.id or 0,
                symbol=symbol,
                direction=crossing,
                window_day=window_day,
            )
            if self._events.dedupe_key_exists(dedupe_key):
                result.skipped_already_fired += 1
                continue

            event = WatchEvent(
                rule_id=rule.id or 0,
                type="price_threshold",
                source=self.SOURCE,
                payload={
                    "symbol": symbol,
                    "direction": crossing,
                    "price": quote.price,
                    "prev_close": quote.prev_close,
                    "pct_change": (
                        (quote.price - quote.prev_close) / quote.prev_close * 100.0
                        if quote.prev_close
                        else None
                    ),
                    "currency": quote.currency,
                    "source_time": quote.source_time.isoformat(),
                    "quality": quote.quality,
                    "rule_config": rule.config,
                },
                dedupe_key=dedupe_key,
                occurred_at=now,
            )
            try:
                self._events.append(event)
            except DedupeKeyConflict:
                # 并发或预检竞态：事件已存在，视为幂等成功
                result.skipped_already_fired += 1
                continue
            result.produced += 1
            self._rules.mark_fired(rule.id or 0, fired_at=now)
        return result


# ── 定时事件源（WO-T1-4）────────────────────────────────────────────────────


class CronEventSource:
    """定时类事件源（晨报 / 盘后复盘）。

    仅交易日产出事件；事件负载只含触发事实（交易日、规则配置），**不含资讯
    内容**——内容由唤醒后的 Agent 运行现取（§4.8）。``dedupe_key`` = 规则 × 交易日。
    """

    SOURCE = "cron"

    def __init__(
        self,
        *,
        rule_store: WatchRuleStore,
        event_store: WatchEventStore,
        calendar: AShareTradingCalendar | None = None,
        clock: Callable[[], datetime] | None = None,  # type: ignore[type-arg]
    ) -> None:
        self._rules = rule_store
        self._events = event_store
        self._calendar = calendar or create_trading_calendar()
        self._now = clock or (lambda: datetime.now(UTC))

    def produce_for(self, rule_type: str) -> list[WatchEvent]:
        """为指定 cron 规则类型产出当日事件（非交易日 / 已产出则跳过）。

        返回实际新增的事件列表（dedupe_key 冲突视为已产出，跳过）。
        """
        if rule_type not in {"daily_briefing", "post_market_review"}:
            raise ValueError(f"cron 事件源不支持规则类型：{rule_type!r}")
        now = self._now()
        beijing = now.astimezone(_CST)
        if not self._calendar.is_trading_day(beijing.date()):
            return []
        window_day = beijing.date().isoformat()
        produced: list[WatchEvent] = []
        for rule in self._rules.list_active_by_type(rule_type):
            dedupe_key = make_cron_dedupe_key(rule_id=rule.id or 0, window_day=window_day)
            if self._events.dedupe_key_exists(dedupe_key):
                continue
            event = WatchEvent(
                rule_id=rule.id or 0,
                type=rule_type,
                source=self.SOURCE,
                payload={
                    "trading_day": window_day,
                    "rule_config": rule.config,
                },
                dedupe_key=dedupe_key,
                occurred_at=now,
            )
            try:
                self._events.append(event)
                produced.append(event)
            except DedupeKeyConflict:
                continue
        return produced


# ── 退避循环（数据源失败指数退避，不中断）────────────────────────────────────


async def run_price_poller_loop(
    *,
    poller: PriceThresholdPoller,
    base_interval_seconds: float,
    max_interval_seconds: float,
    stop_event: asyncio.Event,
) -> None:
    """价格轮询循环：成功按 ``base_interval_seconds`` 节流；失败指数退避（上限 ``max_interval_seconds``）。

    退避在「整轮取价失败」时生效（tick 返回 failed>0 且 produced==0 视为失败）；
    部分标的失败不影响其它标的，不触发整轮退避。
    """
    if base_interval_seconds <= 0:
        raise ValueError("base_interval_seconds must be positive")
    if max_interval_seconds < base_interval_seconds:
        raise ValueError("max_interval_seconds must be >= base_interval_seconds")
    backoff = base_interval_seconds
    while not stop_event.is_set():
        result = await poller.tick()
        failed_round = result.produced == 0 and result.failed > 0
        if failed_round:
            backoff = min(backoff * 2.0, max_interval_seconds)
            interval = backoff
            logger.warning(
                "price poller round failed (failed=%d), backing off %.1fs",
                result.failed,
                interval,
            )
        else:
            backoff = base_interval_seconds
            interval = base_interval_seconds
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            continue
