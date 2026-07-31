import test from 'node:test';
import assert from 'node:assert/strict';

import {
  chinaDateString,
  chinaDateTimeString,
  getChinaTradingDayStatus,
  parseChinaDateTime,
} from '../src/utils/china-time.js';
import { getChinaTradeSession } from '../src/analysis/trading.js';
import { assessDataFreshness, applyFreshnessGuard } from '../src/analysis/freshness.js';
import { mergeQuoteIntoHistory, normalizeSinaVolume } from '../src/data/stock.js';
import { safeNumber } from '../src/analysis/technical.js';
import { money, pct, plainNumber } from '../src/output/formatter.js';

test('所有日期输出固定为北京时间，不依赖宿主时区', () => {
  const instant = new Date('2026-07-23T16:30:45Z');
  assert.equal(chinaDateString(instant), '2026-07-24');
  assert.equal(chinaDateTimeString(instant), '2026-07-24 00:30:45');
});

test('2026 上交所节假日不会误报为可交易', () => {
  const holiday = parseChinaDateTime('2026-10-01', '10:00:00');
  assert.equal(getChinaTradingDayStatus(holiday).isTradingDay, false);
  const session = getChinaTradeSession(holiday);
  assert.equal(session.tradable, false);
  assert.equal(session.calendarVerified, true);
  assert.match(session.label, /节假日休市/);
});

test('盘中行情必须具备当日时间戳和当日K线才判定实时', () => {
  const now = parseChinaDateTime('2026-07-24', '10:01:00');
  const quoteTime = parseChinaDateTime('2026-07-24', '10:00:30');
  const quality = assessDataFreshness({
    assetKind: 'exchange_traded',
    quote: { quoteTime: quoteTime.toISOString(), tradeDate: '2026-07-24' },
    history: [{ date: '2026-07-24', close: 1.25 }],
    now,
  });
  assert.equal(quality.status, 'live');
  assert.equal(quality.allowsDirectionalSignal, true);
  assert.equal(quality.ageSeconds, 30);
});

test('盘中陈旧行情强制把方向信号降为观望', () => {
  const now = parseChinaDateTime('2026-07-24', '10:20:00');
  const quoteTime = parseChinaDateTime('2026-07-24', '10:00:00');
  const quality = assessDataFreshness({
    assetKind: 'exchange_traded',
    quote: { quoteTime: quoteTime.toISOString(), tradeDate: '2026-07-24' },
    history: [{ date: '2026-07-24', close: 1.25 }],
    now,
  });
  const guarded = applyFreshnessGuard({ total: 75, signal: 'strong_buy' }, quality);
  assert.equal(quality.status, 'stale');
  assert.equal(quality.allowsDirectionalSignal, false);
  assert.equal(guarded.signal, 'wait');
  assert.equal(guarded.rawSignal, 'strong_buy');
});

test('实时行情可补齐缺失的当日K线并标记为盘中合成', () => {
  const result = mergeQuoteIntoHistory(
    [{ date: '2026-07-23', close: 1.2, high: 1.21, low: 1.19, volume: 100 }],
    {
      tradeDate: '2026-07-24',
      price: 1.25,
      open: 1.22,
      high: 1.26,
      low: 1.21,
      volume: 80,
      changePct: 4.17,
    },
  );
  assert.equal(result.synthesized, true);
  assert.equal(result.history.at(-1).date, '2026-07-24');
  assert.equal(result.history.at(-1).close, 1.25);
  assert.equal(result.history.at(-1).provisional, true);
});

test('场外基金净值明确标记为非实时', () => {
  const now = parseChinaDateTime('2026-07-24', '10:00:00');
  const quality = assessDataFreshness({
    assetKind: 'open_fund',
    assetType: 'open_fund',
    history: [{ date: '2026-07-23', close: 1.1 }],
    now,
  });
  assert.equal(quality.status, 'nav_t1');
  assert.equal(quality.allowsDirectionalSignal, true);
  assert.match(quality.label, /非实时/);
});

test('缺失数值不会被伪装成 0', () => {
  assert.equal(safeNumber(null), null);
  assert.equal(safeNumber(''), null);
  assert.equal(money(null), 'N/A');
  assert.equal(pct(null), 'N/A');
  assert.equal(plainNumber(null), 'N/A');
});

test('新浪行情成交量从股统一换算为手', () => {
  assert.equal(normalizeSinaVolume('1798058198'), 17980582);
  assert.equal(normalizeSinaVolume(null), null);
});

test('非交易时段缺少行情时间也必须阻断方向信号', () => {
  const now = parseChinaDateTime('2026-07-24', '08:00:00');
  const quality = assessDataFreshness({
    assetKind: 'exchange_traded',
    quote: {},
    history: [{ date: '2026-07-23', close: 1.2 }],
    now,
  });
  assert.equal(quality.status, 'unknown');
  assert.equal(quality.allowsDirectionalSignal, false);
});
