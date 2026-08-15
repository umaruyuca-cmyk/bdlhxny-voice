import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createApp } from '../src/app.js';
import { SearchCache } from '../src/cache.js';
import { AgentRateLimiter } from '../src/rate-limit.js';

const token = 'a'.repeat(32);
const config = {
  agentTokens: new Map([['bdlh_runtime', token]]),
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
        'x-agent-id': 'bdlh_runtime',
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
        'x-agent-id': 'bdlh_runtime',
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
        'x-agent-id': 'bdlh_runtime',
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

test('部分任务失败仍返回固定结果和错误信封', async () => {
  const provider = {
    name: 'fake',
    search: async task => {
      if (task.taskId === 'task-failed') {
        const error = new Error('上游暂时不可用');
        error.code = 'SEARCH_PROVIDER_FAILED';
        throw error;
      }
      return [{
        resultId: 'result-success',
        taskId: task.taskId,
        purposeCode: task.purposeCode,
        title: '证券交易印花税政策',
        url: 'https://www.gov.cn/policy',
        domain: 'www.gov.cn',
        snippet: '政策摘要',
        sourceType: 'OFFICIAL',
        provider: 'fake',
        publishedAt: null,
        retrievedAt: '2026-07-28T00:00:00.000Z',
        relevanceScore: 1,
      }];
    },
  };
  const server = createServer(createApp(config, provider, new SearchCache(1_000)));
  await listen(server);
  try {
    const address = server.address();
    const response = await fetch(`http://127.0.0.1:${address.port}/api/search`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-agent-id': 'bdlh_runtime',
        'x-search-token': token,
      },
      body: JSON.stringify({
        schemaVersion: '1.0',
        tasks: [
          {
            taskId: 'task-success',
            purposeCode: 'POLICY_UPDATE',
            mode: 'GENERAL',
            query: '证券交易印花税政策',
          },
          {
            taskId: 'task-failed',
            purposeCode: 'NEWS_CATALYST',
            mode: 'NEWS',
            query: '市场新闻',
          },
        ],
      }),
    });
    const body = await response.json();
    assert.equal(response.status, 200);
    assert.deepEqual(Object.keys(body).sort(),
      ['errors', 'provider', 'requestId', 'results', 'schemaVersion'].sort());
    assert.deepEqual(Object.keys(body.results[0]).sort(), [
      'domain',
      'provider',
      'publishedAt',
      'purposeCode',
      'relevanceScore',
      'resultId',
      'retrievedAt',
      'snippet',
      'sourceType',
      'taskId',
      'title',
      'url',
    ].sort());
    assert.deepEqual(Object.keys(body.errors[0]).sort(), ['code', 'message', 'taskId']);
    assert.equal(body.results[0].taskId, 'task-success');
    assert.equal(body.errors[0].taskId, 'task-failed');
    assert.equal(body.errors[0].code, 'SEARCH_PROVIDER_FAILED');
  } finally {
    server.close();
  }
});

function listen(server) {
  return new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
}
