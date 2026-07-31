import { SearchWrapperError } from './errors.js';

/**
 * 按 Agent 独立执行固定窗口限流，避免一个调用方耗尽共享搜索资源。
 */
export class AgentRateLimiter {
  constructor(limitPerMinute = 60, now = () => Date.now()) {
    this.limit = Math.max(1, limitPerMinute);
    this.now = now;
    this.windows = new Map();
  }

  /**
   * 消耗一次调用额度，超限时返回稳定的429错误。
   */
  consume(agentId) {
    const timestamp = this.now();
    const current = this.windows.get(agentId);
    if (!current || timestamp >= current.resetAt) {
      this.windows.set(agentId, { count: 1, resetAt: timestamp + 60_000 });
      return;
    }
    if (current.count >= this.limit) {
      throw new SearchWrapperError(429, 'RATE_LIMITED', '当前调用方搜索频率超过限制');
    }
    current.count += 1;
  }
}
