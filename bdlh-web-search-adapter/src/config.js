/**
 * 读取共享搜索服务配置，集中约束调用方、上游地址和资源预算。
 */
export function loadConfig(env = process.env) {
  return {
    port: positiveInt(env.PORT, 3002),
    searxngUrl: normalizeBaseUrl(env.SEARXNG_URL ?? 'http://searxng:8080'),
    searxngEngines: list(env.SEARXNG_ENGINES ?? 'baidu,360search'),
    agentTokens: parseAgentTokens(env.WEB_SEARCH_AGENTS_JSON ?? '{}'),
    requestTimeoutMs: positiveInt(env.WEB_SEARCH_TIMEOUT_MS, 10_000),
    maxBodyBytes: positiveInt(env.WEB_SEARCH_MAX_BODY_BYTES, 32_768),
    maxTasks: boundedInt(env.WEB_SEARCH_MAX_TASKS, 3, 1, 10),
    maxResultsPerTask: boundedInt(env.WEB_SEARCH_MAX_RESULTS, 5, 1, 20),
    cacheTtlMs: positiveInt(env.WEB_SEARCH_CACHE_TTL_MS, 60_000),
    rateLimitPerMinute: boundedInt(env.WEB_SEARCH_RATE_LIMIT_PER_MINUTE, 60, 1, 10_000),
    circuitFailureThreshold: boundedInt(env.WEB_SEARCH_CIRCUIT_FAILURE_THRESHOLD, 5, 1, 100),
    circuitResetMs: positiveInt(env.WEB_SEARCH_CIRCUIT_RESET_MS, 30_000),
  };
}

function parseAgentTokens(raw) {
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error('WEB_SEARCH_AGENTS_JSON 必须是 JSON 对象');
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('WEB_SEARCH_AGENTS_JSON 必须是 JSON 对象');
  }
  const result = new Map();
  for (const [agentId, token] of Object.entries(parsed)) {
    if (!/^[a-zA-Z0-9_-]{1,64}$/.test(agentId) || String(token).length < 32) {
      throw new Error('搜索调用方标识无效或 Token 少于 32 位');
    }
    result.set(agentId, String(token));
  }
  return result;
}

function normalizeBaseUrl(value) {
  return String(value).replace(/\/+$/, '');
}

function list(value) {
  return String(value)
    .split(',')
    .map(item => item.trim())
    .filter(Boolean);
}

function positiveInt(value, fallback) {
  const parsed = Number.parseInt(value ?? fallback, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function boundedInt(value, fallback, min, max) {
  return Math.max(min, Math.min(max, positiveInt(value, fallback)));
}
