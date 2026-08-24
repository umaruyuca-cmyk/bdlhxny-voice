import { authenticate } from './auth.js';
import { errorEnvelope, requestId, successEnvelope, validateRequest } from './contract.js';
import { SearchWrapperError } from './errors.js';
import { defaultLogger } from './log.js';
import { AgentRateLimiter } from './rate-limit.js';

/**
 * 创建共享搜索 HTTP 服务并保持协议、鉴权和 Provider 相互隔离。
 *
 * 可观测性（P0-2）：logger 默认输出结构化 JSON 行到 stdout，可注入 sink
 * 便于测试。运行期记录 request_received/request_completed/request_failed
 * 与 executeTask 的 empty_results 事件。
 */
export function createApp(config, provider, cache,
                          rateLimiter = new AgentRateLimiter(config.rateLimitPerMinute),
                          logger = defaultLogger) {
  return async function handle(request, response) {
    const traceId = requestId(header(request, 'x-request-id'));
    response.setHeader('content-type', 'application/json; charset=utf-8');
    response.setHeader('x-request-id', traceId);
    const startedAt = Date.now();
    const method = request.method;
    const path = pathOnly(request.url);
    logger.debug('request_received', { traceId, method, path });
    try {
      if (method === 'GET' && request.url === '/health') {
        writeJson(response, 200, { status: 'UP', service: 'bdlh-web-search-adapter' });
        return;
      }
      if (method === 'GET' && request.url === '/ready') {
        writeJson(response, 200, { status: 'READY', provider: provider.name });
        return;
      }
      if (method !== 'POST' || path !== '/api/search') {
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
      const executions = await Promise.all(tasks.map(task => executeTask(provider, cache, task, logger)));
      const results = executions.flatMap(item => item.results);
      const errors = executions.flatMap(item => item.errors);
      logger.info('request_completed', {
        traceId, agentId,
        tasks: tasks.length,
        results: results.length,
        errors: errors.length,
        durationMs: Date.now() - startedAt,
      });
      writeJson(response, 200, successEnvelope(traceId, provider.name, results, errors));
    } catch (error) {
      const mapped = error instanceof SearchWrapperError
        ? error
        : new SearchWrapperError(500, 'INTERNAL_ERROR', '搜索服务内部错误');
      logger.warn('request_failed', {
        traceId,
        status: mapped.status,
        code: mapped.code,
        durationMs: Date.now() - startedAt,
      });
      writeJson(response, mapped.status, errorEnvelope(traceId, mapped));
    }
  };
}

async function executeTask(provider, cache, task, logger) {
  const key = JSON.stringify(task);
  const cached = cache.get(key);
  let results;
  let fromCache = false;
  if (cached) {
    results = cached;
    fromCache = true;
  } else {
    try {
      results = await provider.search(task);
      cache.set(key, results);
    } catch (error) {
      // Provider 内部已记录失败日志，这里只转成结构化错误，不重复记录。
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
  // 防御：Provider 契约应返回数组，异常形态归一为空，避免 flatMap 报错。
  if (!Array.isArray(results)) results = [];
  const errors = [];
  // 空结果降级（P0-1）：SearXNG 被反爬时常返回 200 + 空数组，必须显式标记，
  // 不能伪装成"搜索成功且零结果"——否则下游会误判"市场无相关新闻"。
  // cache 命中的空结果同样标记。
  if (results.length === 0) {
    errors.push({
      taskId: task.taskId,
      code: 'EMPTY_RESULTS',
      message: '搜索未返回任何结果（可能被上游反爬或无匹配）',
    });
    logger.info('empty_results', { taskId: task.taskId, query: task.query, fromCache });
  }
  return { results, errors };
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
