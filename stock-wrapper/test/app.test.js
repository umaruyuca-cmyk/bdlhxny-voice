import assert from 'node:assert/strict';
import test from 'node:test';
import { createApp } from '../src/app.js';

const config = {
  internalToken: 'test-token',
  maxBodyBytes: 65_536,
};

test('健康检查不要求内部 Token', async () => {
  await withServer(async baseUrl => {
    const response = await fetch(`${baseUrl}/health`);
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { status: 'UP', service: 'stock-wrapper' });
  });
});

test('单标的接口校验 Token 并返回版本化信封', async () => {
  await withServer(async baseUrl => {
    const response = await fetch(`${baseUrl}/api/v1/stock/analyze`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-internal-token': 'test-token',
        'x-request-id': 'request-1',
      },
      body: JSON.stringify({ symbol: '588200', assetType: 'etf' }),
    });
    const body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(body.success, true);
    assert.equal(body.requestId, 'request-1');
    assert.equal(body.contractVersion, '1.0');
    assert.equal(body.data.command, 'stock');
  });
});

test('非法代码返回结构化 400 错误', async () => {
  await withServer(async baseUrl => {
    const response = await fetch(`${baseUrl}/api/v1/stock/analyze`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-internal-token': 'test-token',
      },
      body: JSON.stringify({ symbol: 'abc' }),
    });
    const body = await response.json();
    assert.equal(response.status, 400);
    assert.equal(body.success, false);
    assert.equal(body.error.code, 'INVALID_SYMBOL');
  });
});

test('业务接口拒绝无 Token 请求', async () => {
  await withServer(async baseUrl => {
    const response = await fetch(`${baseUrl}/api/v1/sector/analyze`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: '{}',
    });
    assert.equal(response.status, 401);
  });
});

test('组合接口只把校验后的真实持仓交给执行器', async () => {
  let captured = null;
  const executor = {
    isReady: () => true,
    execute: async (command, input) => {
      captured = { command, input };
      return {
        schemaVersion: '1.1',
        command,
        timezone: 'Asia/Shanghai',
        asOf: null,
        data: {},
      };
    },
  };
  await withServer(async baseUrl => {
    const response = await fetch(`${baseUrl}/api/v1/portfolio/analyze`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-internal-token': 'test-token',
      },
      body: JSON.stringify({
        monthlyBudget: 5000,
        cash: 12000,
        cashReserveRatio: 0.2,
        positions: [{
          code: '588200',
          name: '科创芯片ETF',
          assetType: 'etf',
          avgCost: 1.2,
          shares: 1000,
          buyDate: '2026-01-02',
          targetWeight: 0.3,
          sector: '半导体',
          riskRole: '进攻',
          databaseId: 99,
        }],
      }),
    });

    assert.equal(response.status, 200);
    assert.equal(captured.command, 'portfolio');
    assert.equal(captured.input.positions[0].code, '588200');
    assert.equal(captured.input.positions[0].databaseId, undefined);
  }, executor);
});

test('组合接口拒绝空持仓，不允许回退示例配置', async () => {
  await withServer(async baseUrl => {
    const response = await fetch(`${baseUrl}/api/v1/portfolio/analyze`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-internal-token': 'test-token',
      },
      body: JSON.stringify({
        monthlyBudget: 5000,
        cash: 0,
        cashReserveRatio: 0.2,
        positions: [],
      }),
    });
    const body = await response.json();

    assert.equal(response.status, 400);
    assert.equal(body.error.code, 'INVALID_POSITIONS');
  });
});

async function withServer(action, customExecutor = null) {
  const executor = customExecutor ?? {
    isReady: () => true,
    execute: async command => ({
      schemaVersion: '1.1',
      command,
      timezone: 'Asia/Shanghai',
      asOf: null,
      data: {},
    }),
  };
  const server = createApp(config, executor);
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  try {
    await action(`http://127.0.0.1:${address.port}`);
  } finally {
    await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  }
}
