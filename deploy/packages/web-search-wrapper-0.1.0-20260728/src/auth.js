import { timingSafeEqual } from 'node:crypto';
import { SearchWrapperError } from './errors.js';

/**
 * 使用调用方独立 Token 校验请求，避免多个 Agent 共享同一凭证。
 */
export function authenticate(agentTokens, agentId, token) {
  const expected = agentTokens.get(String(agentId ?? ''));
  if (!expected || !safeEqual(expected, String(token ?? ''))) {
    throw new SearchWrapperError(401, 'UNAUTHORIZED', '搜索调用凭证无效');
  }
  return String(agentId);
}

function safeEqual(expected, actual) {
  const expectedBuffer = Buffer.from(expected);
  const actualBuffer = Buffer.from(actual);
  return expectedBuffer.length === actualBuffer.length
    && timingSafeEqual(expectedBuffer, actualBuffer);
}
