import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createApp } from '../src/app.js';
import { SearchCache } from '../src/cache.js';
import { AgentRateLimiter } from '../src/rate-limit.js';

const token = 'a'.repeat(32);
const config = {
  agentTokens: new Map([['stockwise', token]]),
  maxBodyBytes: 32_768,
  maxTasks: 3,
  maxResultsPerTask: 5,
};

test('正确调用方获得固定搜索结果', async () => {
  const provider = {
    name: 'fake',
    search: async task => [{
      resultId: 'result-1',
      taskId: task.taskId,
      purposeCode: task.purposeCode,
      title: '测试结果',
      url: 'https://example.com/',
      domain: 'example.com',
      snippet: '摘要',
      sourceType: 'WEB',
      provider: 'fake',
      publishedAt: null,
      retrievedAt: new Date().toISOString(),
      relevanceScore: 1,
    }],
  };
  const server = createServer(createApp(config, provider, new SearchCache(1_000)));
  await listen(server);
  try {
    const address = server.address();
    const response = await fetch(`http://127.0.0.1:${address.port}/api/search`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-agent-id': 'stockwise',
        'x-search-token': token,
      },
      body: JSON.stringify({
        schemaVersion: '1.0',
        tasks: [{
          taskId: 'task-1',
          purposeCode: 'KNOWLEDGE_VERIFY',
          mode: 'GENERAL',
          query: '什么是量价背离',
        }],
      }),
    });
    const body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(body.schemaVersion, '1.0');
    assert.equal(body.results.length, 1);
  } finally {
    server.close();
  }
});

test('错误 Token 返回401', async () => {
  const provider = { name: 'fake', search: async () => [] };
  const server = createServer(createApp(config, provider, new SearchCache(1_000)));
  await listen(server);
  try {
    const address = server.address();
    const response = await fetch(`http://127.0.0.1:${address.port}/api/search`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-agent-id': 'stockwise',
        'x-search-token': 'wrong',
      },
      body: JSON.stringify({ schemaVersion: '1.0', tasks: [] }),
    });
    assert.equal(response.status, 401);
  } finally {
    server.close();
  }
});

test('每个 Agent 独立超限后返回429', async () => {
  const provider = { name: 'fake', search: async () => [] };
  const limiter = new AgentRateLimiter(1);
  const server = createServer(createApp(config, provider, new SearchCache(1_000), limiter));
  await listen(server);
  try {
    const address = server.address();
    const request = () => fetch(`http://127.0.0.1:${address.port}/api/search`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-agent-id': 'stockwise',
        'x-search-token': token,
      },
      body: JSON.stringify({
        schemaVersion: '1.0',
        tasks: [{
          taskId: 'task-rate',
          purposeCode: 'KNOWLEDGE_VERIFY',
          mode: 'GENERAL',
          query: '量价背离',
        }],
      }),
    });
    assert.equal((await request()).status, 200);
    assert.equal((await request()).status, 429);
  } finally {
    server.close();
  }
});

function listen(server) {
  return new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
}
