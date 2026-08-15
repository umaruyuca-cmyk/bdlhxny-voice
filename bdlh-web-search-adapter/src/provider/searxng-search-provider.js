import { SearchWrapperError } from '../errors.js';
import { normalizeResults } from '../normalize/search-result-normalizer.js';

/**
 * 通过 SearXNG 聚合国内搜索源并输出固定结果。
 */
export class SearxngSearchProvider {
  constructor(config, fetchImpl = fetch) {
    this.config = config;
    this.fetchImpl = fetchImpl;
    this.name = 'searxng';
    this.failureCount = 0;
    this.openUntil = 0;
  }

  /**
   * 执行单个结构化任务，不接受用户完整问题。
   */
  async search(task) {
    if (Date.now() < this.openUntil) {
      throw new SearchWrapperError(503, 'SEARCH_CIRCUIT_OPEN', 'SearXNG 暂时不可用，请稍后重试');
    }
    const url = new URL('/search', `${this.config.searxngUrl}/`);
    url.searchParams.set('q', buildQuery(task));
    url.searchParams.set('format', 'json');
    url.searchParams.set('language', task.language);
    url.searchParams.set('categories', task.mode === 'NEWS' ? 'news' : 'general');
    if (this.config.searxngEngines.length > 0) {
      url.searchParams.set('engines', this.config.searxngEngines.join(','));
    }
    const timeRange = mapTimeRange(task.freshnessDays);
    if (timeRange) url.searchParams.set('time_range', timeRange);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.config.requestTimeoutMs);
    try {
      const response = await this.fetchImpl(url, {
        headers: { accept: 'application/json' },
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new SearchWrapperError(502, 'SEARCH_PROVIDER_FAILED', `SearXNG 返回 HTTP ${response.status}`);
      }
      const body = await response.json();
      const results = normalizeResults(task, body.results, this.name);
      this.failureCount = 0;
      this.openUntil = 0;
      return results;
    } catch (error) {
      this.recordFailure();
      if (error instanceof SearchWrapperError) throw error;
      const code = error?.name === 'AbortError' ? 'SEARCH_PROVIDER_TIMEOUT' : 'SEARCH_PROVIDER_FAILED';
      throw new SearchWrapperError(502, code, code === 'SEARCH_PROVIDER_TIMEOUT'
        ? 'SearXNG 请求超时'
        : 'SearXNG 请求失败');
    } finally {
      clearTimeout(timeout);
    }
  }

  recordFailure() {
    this.failureCount += 1;
    const threshold = this.config.circuitFailureThreshold ?? 5;
    if (this.failureCount >= threshold) {
      this.openUntil = Date.now() + (this.config.circuitResetMs ?? 30_000);
      this.failureCount = 0;
    }
  }
}

function buildQuery(task) {
  if (task.includeDomains.length === 0) return task.query;
  const domains = task.includeDomains.map(domain => `site:${domain}`).join(' OR ');
  return `${task.query} (${domains})`;
}

function mapTimeRange(days) {
  if (days == null) return null;
  if (days <= 1) return 'day';
  if (days <= 31) return 'month';
  return 'year';
}
