import test from 'node:test';
import assert from 'node:assert/strict';
import { SearxngSearchProvider } from '../src/provider/searxng-search-provider.js';

const task = {
  taskId: 'task-provider',
  purposeCode: 'KNOWLEDGE_VERIFY',
  mode: 'GENERAL',
  query: '量价背离',
  language: 'zh-CN',
  freshnessDays: null,
  includeDomains: [],
  excludeDomains: [],
  maxResults: 5,
};

test('连续失败达到阈值后熔断且不再请求上游', async () => {
  let calls = 0;
  const provider = new SearxngSearchProvider({
    searxngUrl: 'http://searxng:8080',
    searxngEngines: ['baidu', '360search'],
    requestTimeoutMs: 1_000,
    circuitFailureThreshold: 1,
    circuitResetMs: 30_000,
  }, async () => {
    calls += 1;
    throw new Error('upstream failed');
  });

  await assert.rejects(provider.search(task), error => error.code === 'SEARCH_PROVIDER_FAILED');
  await assert.rejects(provider.search(task), error => error.code === 'SEARCH_CIRCUIT_OPEN');
  assert.equal(calls, 1);
});
