import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizeSkillOutput } from '../src/contract.js';

test('保留已有 stock JSON 契约', () => {
  const source = {
    schemaVersion: '1.1',
    command: 'stock',
    timezone: 'Asia/Shanghai',
    asOf: '2026-07-28T10:00:00+08:00',
    dataQuality: { status: 'verified', asOf: '2026-07-28T10:00:00+08:00' },
    data: {},
    methodology: {
      id: 'stockwise-objective-analysis',
      version: '1.0.0',
      rules: [],
    },
    decisionBasis: { verdict: 'hold' },
  };
  assert.deepEqual(normalizeSkillOutput('stock', JSON.stringify(source)), source);
});

test('保留 Skill 原生统一契约', () => {
  const source = {
    schemaVersion: '1.1',
    command: 'quant',
    timezone: 'Asia/Shanghai',
    asOf: '2026-07-28',
    request: {},
    dataQuality: { status: 'verified', asOf: '2026-07-28' },
    data: { metrics: {} },
    sources: {},
    methodology: {
      id: 'stockwise-objective-analysis',
      version: '1.0.0',
      rules: [],
    },
    decisionBasis: { verdict: 'risk_on' },
  };
  assert.deepEqual(normalizeSkillOutput('quant', JSON.stringify(source)), source);
});

test('拒绝把 portfolio 文本猜测为成功契约', () => {
  assert.throws(
    () => normalizeSkillOutput('portfolio', '持仓分析结果'),
    error => error.code === 'SKILL_INVALID_JSON',
  );
});

test('拒绝缺少数据时间与质量信息的 JSON', () => {
  assert.throws(
    () => normalizeSkillOutput('sector', JSON.stringify({
      schemaVersion: '1.1',
      command: 'sector',
      timezone: 'Asia/Shanghai',
      data: {},
    })),
    error => error.code === 'SKILL_AS_OF_MISSING',
  );
});

test('拒绝缺少方法论和决策依据的成功 JSON', () => {
  assert.throws(
    () => normalizeSkillOutput('stock', JSON.stringify({
      schemaVersion: '1.1',
      command: 'stock',
      timezone: 'Asia/Shanghai',
      asOf: '2026-07-29 10:00:00',
      dataQuality: { status: 'verified' },
      data: {},
    })),
    error => error.code === 'SKILL_METHODOLOGY_MISSING',
  );
});

test('拒绝缺少可复算分项的旧版板块热度', () => {
  assert.throws(
    () => normalizeSkillOutput('sector', JSON.stringify({
      schemaVersion: '1.1',
      command: 'sector',
      timezone: 'Asia/Shanghai',
      asOf: '2026-08-01 10:00:00',
      dataQuality: { status: 'verified' },
      data: { sectors: [{ name: '半导体', heatScore: 88 }] },
      methodology: {
        id: 'stockwise-objective-analysis',
        version: '1.0.0',
        rules: [],
      },
      decisionBasis: { verdict: 'relative_ranking_only' },
    })),
    error => error.code === 'SECTOR_HEAT_CONTRACT_INVALID',
  );
});
