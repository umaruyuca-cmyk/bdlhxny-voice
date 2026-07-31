import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { buildStockJsonOutput } from '../src/index.js';

const skillRoot = fileURLToPath(new URL('..', import.meta.url));

test('stock 子命令帮助可执行且包含 JSON 选项', () => {
  const result = spawnSync(process.execPath, ['bin/stock-analysis.js', 'stock', '--help'], {
    cwd: skillRoot,
    encoding: 'utf8',
  });

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /--json/);
  assert.match(result.stdout, /结构化 JSON/);
  assert.match(result.stdout, /资产类型/);
});

test('buildStockJsonOutput 生成稳定的机器可读数据契约', () => {
  const data = {
    code: '588200',
    name: '示例 ETF',
    assetKind: 'exchange_traded',
    quote: { price: 1.234, changePct: 0.012 },
    history: [{ date: '2026-07-24', close: 1.234 }],
    technical: { close: 1.234 },
    score: { total: 55, signal: 'hold' },
    chase: { level: 'safe', reasons: [] },
    dataQuality: { asOf: '2026-07-24 15:00:00', status: 'previous_close' },
  };
  const output = buildStockJsonOutput({
    data,
    profile: { key: 'standard', label: '客观标准', description: '示例' },
    session: { key: 'closed', label: '已收盘', tradable: false },
    lotTrade: { shares: 100, amount: 123.4 },
    tradingRisk: null,
    options: { asset: 'etf', days: 120 },
  });
  const reparsed = JSON.parse(JSON.stringify(output));

  assert.equal(reparsed.schemaVersion, '1.1');
  assert.equal(reparsed.command, 'stock');
  assert.equal(reparsed.timezone, 'Asia/Shanghai');
  assert.equal(reparsed.asOf, data.dataQuality.asOf);
  assert.deepEqual(reparsed.request, { code: '588200', asset: 'etf', days: 120 });
  assert.deepEqual(reparsed.data, data);
  assert.equal(reparsed.trading.lotTrade.shares, 100);
  assert.equal(reparsed.trading.positionRisk, null);
  assert.equal(reparsed.methodology.rules.some(rule => rule.ruleId === 'SCORE-HEURISTIC-001'), true);
  assert.equal(reparsed.decisionBasis.evidence[0].caveat.includes('不代表胜率'), true);
  assert.equal(reparsed.decisionBasis.gates[0].ruleId, 'DATA-FRESH-001');
});
