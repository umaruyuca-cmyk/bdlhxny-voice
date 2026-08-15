import { authenticate } from './auth.js';
import { errorEnvelope, requestId, successEnvelope, validateRequest } from './contract.js';
import { SearchWrapperError } from './errors.js';
import { AgentRateLimiter } from './rate-limit.js';

/**
 * 创建共享搜索 HTTP 服务并保持协议、鉴权和 Provider 相互隔离。
 */
export function createApp(config, provider, cache,
                          rateLimiter = new AgentRateLimiter(config.rateLimitPerMinute)) {
  return async function handle(request, response) {
    const traceId = requestId(header(request, 'x-request-id'));
    response.setHeader('content-type', 'application/json; charset=utf-8');
    response.setHeader('x-request-id', traceId);
    try {
      if (request.method === 'GET' && request.url === '/health') {
        writeJson(response, 200, { status: 'UP', service: 'bdlh-web-search-adapter' });
        return;
      }
      if (request.method === 'GET' && request.url === '/ready') {
        writeJson(response, 200, { status: 'READY', provider: provider.name });
        return;
      }
      if (request.method !== 'POST' || pathOnly(request.url) !== '/api/search') {
        throw new SearchWrapperError(404, 'NOT_FOUND', '接口不存在');
      }

      // 1. 先鉴权和限制请求体，再解析结构化任务。
      const agentId = authenticate(
        config.agentTokens,
        header(request, 'x-agent-id'),
        header(request, 'x-search-token'),
      );
      rateLimiter.consume(agentId);
      const body = await readJsonBody(request, config.maxBodyBytes);
      const tasks = validateRequest(body, config);

      // 2. 每个任务独立失败，保留其他任务的有效结果。
      const executions = await Promise.all(tasks.map(task => executeTask(provider, cache, task)));
      const results = executions.flatMap(item => item.results);
      const errors = executions.flatMap(item => item.errors);
      writeJson(response, 200, successEnvelope(traceId, provider.name, results, errors));
    } catch (error) {
      const mapped = error instanceof SearchWrapperError
        ? error
        : new SearchWrapperError(500, 'INTERNAL_ERROR', '搜索服务内部错误');
      writeJson(response, mapped.status, errorEnvelope(traceId, mapped));
    }
  };
}

async function executeTask(provider, cache, task) {
  const key = JSON.stringify(task);
  const cached = cache.get(key);
  if (cached) return { results: cached, errors: [] };
  try {
    const results = await provider.search(task);
    cache.set(key, results);
    return { results, errors: [] };
  } catch (error) {
    return {
      results: [],
      errors: [{
        taskId: task.taskId,
        code: error.code ?? 'SEARCH_PROVIDER_FAILED',
        message: error.message ?? '搜索任务执行失败',
      }],
    };
  }
}

function readJsonBody(request, maxBytes) {
  return new Promise((resolve, reject) => {
    let bytes = 0;
    let text = '';
    let rejected = false;
    request.on('data', chunk => {
      if (rejected) return;
      bytes += chunk.length;
      if (bytes > maxBytes) {
        rejected = true;
        reject(new SearchWrapperError(413, 'BODY_TOO_LARGE', '请求体超过大小限制'));
        return;
      }
      text += chunk.toString('utf8');
    });
    request.on('end', () => {
      if (rejected) return;
      try {
        resolve(JSON.parse(text || '{}'));
      } catch {
        reject(new SearchWrapperError(400, 'INVALID_JSON', '请求体不是有效 JSON'));
      }
    });
    request.on('error', () => reject(new SearchWrapperError(400, 'REQUEST_READ_FAILED', '读取请求失败')));
  });
}

function writeJson(response, status, body) {
  response.statusCode = status;
  response.end(JSON.stringify(body));
}

function pathOnly(url) {
  return String(url ?? '').split('?', 1)[0];
}

function header(request, name) {
  const value = request.headers[name];
  return Array.isArray(value) ? value[0] : value;
}
