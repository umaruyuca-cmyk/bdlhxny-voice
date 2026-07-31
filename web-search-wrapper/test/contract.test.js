import test from 'node:test';
import assert from 'node:assert/strict';
import { validateRequest } from '../src/contract.js';

const config = { maxTasks: 3, maxResultsPerTask: 5 };

test('接受通用版本化搜索任务', () => {
  const tasks = validateRequest({
    schemaVersion: '1.0',
    tasks: [{
      taskId: 'task-1',
      purposeCode: 'POLICY_UPDATE',
      mode: 'GENERAL',
      query: '证券交易印花税 最新政策',
      language: 'zh-CN',
      freshnessDays: 30,
      includeDomains: ['gov.cn'],
      excludeDomains: [],
      maxResults: 5,
    }],
  }, config);

  assert.equal(tasks.length, 1);
  assert.equal(tasks[0].purposeCode, 'POLICY_UPDATE');
});

test('拒绝股票领域私有字段', () => {
  assert.throws(() => validateRequest({
    schemaVersion: '1.0',
    tasks: [{
      taskId: 'task-1',
      purposeCode: 'NEWS_CATALYST',
      query: '贵州茅台 新闻',
      symbol: '600519',
    }],
  }, config), /未知字段/);
});
