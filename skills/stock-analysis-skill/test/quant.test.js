import test from 'node:test';
import assert from 'node:assert/strict';

import {
  allocateInverseVolatility,
  backtestMomentumRotation,
  calculateAnnualizedVolatility,
  calculateMomentum,
  evaluateMarketRegime,
  rankMomentumUniverse,
  validateQuantConfig,
} from '../src/analysis/quant.js';
import { completedDailyBars } from '../src/index.js';
import { parseChinaDateTime } from '../src/utils/china-time.js';

function makeHistory({ days = 260, dailyReturn = 0.001, start = 100, volatility = 0 }) {
  const rows = [];
  let close = start;
  const origin = new Date('2024-01-01T00:00:00Z');
  for (let index = 0; index < days; index += 1) {
    close *= 1 + dailyReturn + (index % 2 === 0 ? volatility : -volatility);
    rows.push({
      date: new Date(origin.getTime() + index * 86400000).toISOString().slice(0, 10),
      open: close,
      close,
      high: close,
      low: close,
      amount: 1e8,
    });
  }
  return rows;
}

test('动量只使用指定回看窗口', () => {
  const history = makeHistory({ days: 121, dailyReturn: 0.001 });
  const expected = history.at(-1).close / history.at(-21).close - 1;
  assert.ok(Math.abs(calculateMomentum(history, 20) - expected) < 1e-12);
});

test('波动率和排名为确定性代码计算', () => {
  const steady = makeHistory({ dailyReturn: 0.001, volatility: 0.0002 });
  const fast = makeHistory({ dailyReturn: 0.002, volatility: 0.0004 });
  assert.ok(calculateAnnualizedVolatility(fast) > calculateAnnualizedVolatility(steady));
  const ranking = rankMomentumUniverse([
    { code: 'A', history: steady },
    { code: 'B', history: fast },
  ]);
  assert.equal(ranking[0].code, 'B');
});

test('逆波动率配置遵守单品种上限并保留现金', () => {
  const ranking = rankMomentumUniverse([
    { code: 'A', history: makeHistory({ dailyReturn: 0.001, volatility: 0.001 }) },
    { code: 'B', history: makeHistory({ dailyReturn: 0.0012, volatility: 0.002 }) },
    { code: 'C', history: makeHistory({ dailyReturn: 0.0014, volatility: 0.003 }) },
  ]);
  const allocation = allocateInverseVolatility(ranking, {
    selectCount: 3,
    maxAssetWeight: 0.35,
    targetAnnualVolatility: 0.05,
  });
  assert.ok(Object.values(allocation.weights).every((weight) => weight <= 0.3500001));
  assert.ok(allocation.cashWeight >= 0);
  assert.ok(Object.values(allocation.weights).reduce((sum, value) => sum + value, 0) <= 1);
});

test('回测信号日期早于生效日期并计入交易成本', () => {
  const assets = [
    { code: 'A', history: makeHistory({ days: 300, dailyReturn: 0.001, volatility: 0.001 }) },
    { code: 'B', history: makeHistory({ days: 300, dailyReturn: 0.0005, volatility: 0.002 }) },
  ];
  const result = backtestMomentumRotation(assets, {
    selectCount: 1,
    maxAssetWeight: 1,
    targetAnnualVolatility: 1,
    transactionCostRate: 0.001,
  });
  assert.ok(result.rebalances.length > 0);
  assert.ok(result.rebalances.every((item) => item.signalDate < item.effectiveDate));
  assert.ok(result.metrics.estimatedCostDrag > 0);
  assert.ok(result.metrics.finalEquity > 1);
  assert.equal(result.benchmarkMetrics, null);
});

test('市场过滤在基准跌破MA200时转为现金', () => {
  const risingAsset = { code: 'A', history: makeHistory({ days: 320, dailyReturn: 0.001 }) };
  const fallingBenchmark = {
    code: 'BM',
    history: makeHistory({ days: 320, dailyReturn: -0.001, volatility: 0.0002 }),
  };
  assert.equal(evaluateMarketRegime(fallingBenchmark.history).eligible, false);
  const result = backtestMomentumRotation(
    [risingAsset],
    { selectCount: 1, maxAssetWeight: 1, targetAnnualVolatility: 1 },
    fallingBenchmark,
  );
  assert.deepEqual(result.currentAllocation.weights, {});
  assert.equal(result.currentAllocation.cashWeight, 1);
  assert.ok(result.benchmarkMetrics.totalReturn < 0);
});

test('盘中量化回测剔除尚未完成的北京时间当日K线', () => {
  const history = [
    { date: '2026-07-23', close: 1 },
    { date: '2026-07-24', close: 1.1 },
  ];
  const intraday = parseChinaDateTime('2026-07-24', '10:00:00');
  const afterClose = parseChinaDateTime('2026-07-24', '15:01:00');
  assert.deepEqual(completedDailyBars(history, intraday).map((row) => row.date), ['2026-07-23']);
  assert.deepEqual(completedDailyBars(history, afterClose).map((row) => row.date), ['2026-07-23', '2026-07-24']);
});

test('拒绝危险或无效的量化参数', () => {
  assert.throws(() => validateQuantConfig({ rebalanceEvery: 0 }), /正整数/);
  assert.throws(() => validateQuantConfig({ maxAssetWeight: 1.2 }), /范围/);
  assert.throws(() => validateQuantConfig({ transactionCostRate: -0.1 }), /范围/);
});
