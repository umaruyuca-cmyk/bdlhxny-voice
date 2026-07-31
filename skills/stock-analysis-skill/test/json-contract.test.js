import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  buildPortfolioJsonOutput,
  buildQuantJsonOutput,
  buildSectorJsonOutput,
} from '../src/index.js';
import {
  buildErrorContract,
  buildSuccessContract,
} from '../src/output/json-contract.js';
import {
  calculateSectorHeatBreakdown,
  calculateSectorHeatScore,
} from '../src/data/sector.js';

const skillRoot = fileURLToPath(new URL('..', import.meta.url));

test('统一成功信封固定版本、时区和数据质量字段', () => {
  const result = buildSuccessContract('sector', {
    asOf: '2026-07-29 10:00:00',
    dataQuality: { allowsDirectionalSignal: true },
    data: { sectors: [] },
  });

  assert.equal(result.schemaVersion, '1.1');
  assert.equal(result.command, 'sector');
  assert.equal(result.timezone, 'Asia/Shanghai');
  assert.equal(result.dataQuality.asOf, result.asOf);
  assert.equal(result.dataQuality.allowsDirectionalSignal, true);
  assert.deepEqual(result.data.sectors, []);
  assert.equal(result.methodology.id, 'stockwise-objective-analysis');
  assert.equal(result.methodology.version, '1.1.0');
  assert.equal(result.methodology.rules[0].ruleId, 'SECTOR-HEAT-001');
});

test('sector 不再返回文本包装而是原生排名数据', () => {
  const result = buildSectorJsonOutput({
    type: 'industry',
    sectors: [{ code: 'BK0001', name: '半导体' }],
    leaders: [],
    laggards: [],
    rotation: { strong5d: [], weak5d: [], fundDivergence: [] },
    dataTime: '2026-07-29 10:00:00',
    historyCoverage: { requested: 1, succeeded: 1 },
    warnings: [],
  }, { limit: 20 });

  assert.equal(result.command, 'sector');
  assert.equal(result.asOf, '2026-07-29 10:00:00');
  assert.equal(result.data.sectors[0].name, '半导体');
  assert.equal(result.dataQuality.status, 'verified');
  assert.equal(result.dataQuality.allowsDirectionalSignal, true);
  assert.equal(result.data.format, undefined);
  assert.equal(result.decisionBasis.verdict, 'relative_ranking_only');
});

test('quant 返回统一信封并公开资产数据源', () => {
  const result = buildQuantJsonOutput({
    result: {
      currentRegime: { asOf: '2026-07-28' },
      period: { end: '2026-07-28' },
      config: { selectCount: 2 },
      metrics: {},
    },
    codes: ['510300', '159915'],
    benchmarkCode: '510300',
    fetched: [
      { code: '510300', source: 'eastmoney' },
      { code: '159915', source: 'tencent' },
    ],
    benchmark: { source: 'eastmoney' },
  });

  assert.equal(result.command, 'quant');
  assert.equal(result.data.metrics != null, true);
  assert.equal(result.sources.assets['159915'], 'tencent');
  assert.equal(result.decisionBasis.evidence[0].ruleId, 'QUANT-MOM-001');
});

test('portfolio 返回真实持仓、汇总和逐标的数据质量', () => {
  const quality = {
    status: 'live',
    asOf: '2026-07-29 10:00:00',
    allowsDirectionalSignal: true,
    warnings: [],
  };
  const result = buildPortfolioJsonOutput({
    portfolio: {
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
      __meta: { warnings: [], filePath: '不得输出的本机路径' },
    },
    market: { dataTime: '2026-07-29 10:00:00' },
    sectorData: {
      dataTime: null,
      sectors: [],
      warnings: ['板块数据暂不可用：上游连接重置'],
    },
    holdings: [{
      position: { code: '588200' },
      stockData: { dataQuality: quality, sources: { quote: 'eastmoney' } },
    }],
    summary: { totalValue: 13200 },
    allocation: { plan: [] },
    overseas: { indices: [] },
    sectorLimit: 10,
  });

  assert.equal(result.command, 'portfolio');
  assert.equal(result.data.portfolio.positions[0].code, '588200');
  assert.equal(result.dataQuality.holdings[0].allowsDirectionalSignal, true);
  assert.equal(result.dataQuality.warnings.includes('板块数据暂不可用：上游连接重置'), true);
  assert.equal(result.sources.sector, null);
  assert.equal(JSON.stringify(result).includes('不得输出的本机路径'), false);
  assert.equal(result.decisionBasis.limitations.length > 0, true);
});

test('板块热度使用同类横截面分位并公开每项贡献', () => {
  const universe = [
    { changePct: 1, change5d: 2, change20d: 3, mainNetInflow: 5, turnoverRate: 2 },
    { changePct: 2, change5d: 4, change20d: 6, mainNetInflow: 10, turnoverRate: 3 },
    { changePct: 3, change5d: 6, change20d: 9, mainNetInflow: 15, turnoverRate: 4 },
  ];
  const breakdown = calculateSectorHeatBreakdown(universe[1], universe);

  assert.equal(calculateSectorHeatScore(universe[1], universe), 50);
  assert.equal(breakdown.formulaVersion, 'sector-heat-v2');
  assert.equal(breakdown.normalization, 'cross_sectional_percentile');
  assert.equal(breakdown.components.daily.raw, 2);
  assert.equal(breakdown.components.daily.normalized, 50);
  assert.equal(breakdown.components.daily.contribution, 17.5);
});

test('缺少20日K线时不再使用5日趋势冒充', () => {
  const sector = {
    changePct: 2,
    change5d: 4,
    change20d: null,
    mainNetInflow: 10,
    turnoverRate: 3,
  };
  const breakdown = calculateSectorHeatBreakdown(sector, [sector]);

  assert.equal(breakdown.missingComponents.includes('twentyDay'), true);
  assert.equal(breakdown.availableWeight, 0.85);
  assert.equal(breakdown.components.twentyDay, undefined);
});

test('机器模式错误使用非零退出码和结构化 stderr', () => {
  const result = spawnSync(process.execPath, [
    'bin/stock-analysis.js',
    '--config',
    'missing-user-portfolio.json',
    'portfolio',
    '--json',
  ], {
    cwd: skillRoot,
    encoding: 'utf8',
  });

  assert.notEqual(result.status, 0);
  assert.equal(result.stdout, '');
  const error = JSON.parse(result.stderr);
  assert.equal(error.schemaVersion, '1.1');
  assert.equal(error.command, 'portfolio');
  assert.equal(error.error.code, 'PORTFOLIO_CONFIG_NOT_FOUND');
});

test('错误信封不包含堆栈', () => {
  const result = buildErrorContract('stock', Object.assign(new Error('数据源失败'), {
    code: 'DATA_SOURCE_FAILED',
  }));

  assert.equal(result.error.code, 'DATA_SOURCE_FAILED');
  assert.equal(result.error.message, '数据源失败');
  assert.equal(result.error.stack, undefined);
});
