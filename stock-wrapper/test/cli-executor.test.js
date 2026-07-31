import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { StockSkillCliExecutor } from '../src/cli-executor.js';

/**
 * 验证真实持仓通过单次临时配置交给 Skill，并在执行结束后立即清除。
 */
test('组合执行应传递真实配置并删除临时文件', async t => {
  const skillPath = fs.mkdtempSync(path.join(os.tmpdir(), 'stockwise-fake-skill-'));
  t.after(() => fs.rmSync(skillPath, { recursive: true, force: true }));
  const cliScript = path.join(skillPath, 'fake-cli.mjs');
  fs.writeFileSync(cliScript, `
import fs from 'node:fs';
const configIndex = process.argv.indexOf('--config');
const configPath = process.argv[configIndex + 1];
const portfolio = JSON.parse(fs.readFileSync(configPath, 'utf8'));
console.log(JSON.stringify({
  schemaVersion: '1.1',
  command: 'portfolio',
  timezone: 'Asia/Shanghai',
  asOf: '2026-07-29 10:00:00',
  dataQuality: {
    status: 'verified',
    asOf: '2026-07-29 10:00:00',
    allowsDirectionalSignal: true,
    provisional: false,
    warnings: []
  },
  methodology: {
    id: 'stockwise-objective-analysis',
    version: '1.0.0',
    rules: []
  },
  decisionBasis: { verdict: 'portfolio_analysis_available' },
  data: { configPath, portfolio }
}));
`, { encoding: 'utf8', flag: 'wx' });
  const executor = new StockSkillCliExecutor({
    nodeBin: process.execPath,
    skillPath,
    cliScript,
    timeoutMs: 5_000,
    maxOutputBytes: 65_536,
    maxConcurrency: 1,
  });
  const input = {
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
    }],
  };

  const result = await executor.execute('portfolio', input);

  assert.deepEqual(result.data.portfolio, input);
  assert.equal(fs.existsSync(result.data.configPath), false);
  assert.equal(executor.activeExecutions, 0);
});

test('执行器应透传 Skill 结构化错误码而不是隐藏为黑箱失败', async t => {
  const skillPath = fs.mkdtempSync(path.join(os.tmpdir(), 'stockwise-error-skill-'));
  t.after(() => fs.rmSync(skillPath, { recursive: true, force: true }));
  const cliScript = path.join(skillPath, 'error-cli.mjs');
  fs.writeFileSync(cliScript, `
process.stderr.write(JSON.stringify({
  schemaVersion: '1.1',
  command: 'stock',
  timezone: 'Asia/Shanghai',
  asOf: null,
  error: {
    code: 'DATA_SOURCE_UNAVAILABLE',
    message: '行情数据源不可用'
  }
}));
process.exitCode = 1;
`, { encoding: 'utf8', flag: 'wx' });
  const executor = new StockSkillCliExecutor({
    nodeBin: process.execPath,
    skillPath,
    cliScript,
    timeoutMs: 5_000,
    maxOutputBytes: 65_536,
    maxConcurrency: 1,
  });

  await assert.rejects(
    () => executor.execute('stock', { symbol: '588200', assetType: 'etf' }),
    error => error.code === 'DATA_SOURCE_UNAVAILABLE'
      && error.message === '行情数据源不可用'
      && error.details.exitCode === 1,
  );
});
