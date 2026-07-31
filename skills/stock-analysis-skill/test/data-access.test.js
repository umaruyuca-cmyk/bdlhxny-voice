import assert from 'node:assert/strict';
import test from 'node:test';

import {
  isRetryableRequestError,
  retryDelayMs,
} from '../src/utils/api.js';
import { mapWithConcurrency } from '../src/utils/concurrency.js';
import {
  getMarketPrefix,
  isSupportedIndexCode,
  toEastmoneySecid,
} from '../src/data/stock.js';

test('只对网络错误、限流和服务端临时错误进行重试', () => {
  assert.equal(isRetryableRequestError({ code: 'ECONNRESET' }), true);
  assert.equal(isRetryableRequestError({ response: { status: 429 } }), true);
  assert.equal(isRetryableRequestError({ response: { status: 503 } }), true);
  assert.equal(isRetryableRequestError({ response: { status: 400 } }), false);
  assert.equal(isRetryableRequestError({ response: { status: 403 } }), false);
});

test('退避时间包含上限受控的随机抖动并尊重 Retry-After', () => {
  assert.equal(retryDelayMs(1, {}, () => 0), 500);
  assert.equal(retryDelayMs(2, {}, () => 1), 1250);
  assert.equal(retryDelayMs(1, { response: { headers: { 'retry-after': '3' } } }), 3000);
});

test('受控映射不会超过给定并发数且保持输入顺序', async () => {
  let active = 0;
  let peak = 0;
  const result = await mapWithConcurrency([1, 2, 3, 4, 5], 2, async (value) => {
    active += 1;
    peak = Math.max(peak, active);
    await new Promise((resolve) => setTimeout(resolve, 5));
    active -= 1;
    return value * 10;
  });

  assert.equal(peak, 2);
  assert.deepEqual(result, [10, 20, 30, 40, 50]);
});

test('指数基准使用明确市场映射，不再把000300当成深圳普通证券', () => {
  assert.equal(isSupportedIndexCode('000300'), true);
  assert.deepEqual(getMarketPrefix('000300', { instrumentType: 'index' }), {
    eastmoney: '1',
    tencent: 'sh',
    suffix: 'SH',
  });
  assert.equal(toEastmoneySecid('000300', { instrumentType: 'index' }), '1.000300');
  assert.throws(
    () => getMarketPrefix('123456', { instrumentType: 'index' }),
    /暂不支持指数代码/,
  );
});
