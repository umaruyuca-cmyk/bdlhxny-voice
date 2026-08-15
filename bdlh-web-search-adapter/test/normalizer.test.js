import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeResults } from '../src/normalize/search-result-normalizer.js';

test('清理跟踪参数、HTML并按URL去重', () => {
  const task = {
    taskId: 'task-1',
    purposeCode: 'NEWS_CATALYST',
    includeDomains: [],
    excludeDomains: [],
    maxResults: 5,
  };
  const results = normalizeResults(task, [
    {
      title: '<b>贵州茅台</b>',
      url: 'https://example.com/news?id=1&utm_source=test',
      content: '<p>公告摘要</p>',
      score: 1,
    },
    {
      title: '重复结果',
      url: 'https://example.com/news?id=1',
      content: '重复',
      score: 0.5,
    },
  ], 'fake', new Date('2026-07-28T00:00:00Z'));

  assert.equal(results.length, 1);
  assert.equal(results[0].title, '贵州茅台');
  assert.equal(results[0].url, 'https://example.com/news?id=1');
});
