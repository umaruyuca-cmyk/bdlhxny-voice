import { randomUUID } from 'node:crypto';
import { SearchWrapperError } from './errors.js';

const ROOT_FIELDS = new Set(['schemaVersion', 'tasks']);
const TASK_FIELDS = new Set([
  'taskId',
  'purposeCode',
  'mode',
  'query',
  'language',
  'freshnessDays',
  'includeDomains',
  'excludeDomains',
  'maxResults',
]);

/**
 * 校验跨 Agent 搜索协议并拒绝股票私有字段和未知字段。
 */
export function validateRequest(body, config) {
  assertObject(body, '请求体必须是 JSON 对象');
  rejectUnknown(body, ROOT_FIELDS, '请求体');
  if (body.schemaVersion !== '1.0') {
    throw new SearchWrapperError(400, 'UNSUPPORTED_SCHEMA_VERSION', '仅支持 schemaVersion 1.0');
  }
  if (!Array.isArray(body.tasks) || body.tasks.length < 1 || body.tasks.length > config.maxTasks) {
    throw new SearchWrapperError(400, 'INVALID_TASK_COUNT', `tasks 数量必须在 1 到 ${config.maxTasks} 之间`);
  }
  const seen = new Set();
  return body.tasks.map(task => validateTask(task, config, seen));
}

/**
 * 生成固定成功信封，使所有调用方只依赖稳定协议。
 */
export function successEnvelope(requestId, provider, results, errors) {
  return {
    schemaVersion: '1.0',
    requestId,
    provider,
    results,
    errors,
  };
}

/**
 * 生成固定错误信封，不泄露上游响应和调用凭证。
 */
export function errorEnvelope(requestId, error) {
  return {
    schemaVersion: '1.0',
    requestId,
    error: {
      code: error.code ?? 'INTERNAL_ERROR',
      message: error.message ?? '搜索服务内部错误',
      details: error.details ?? null,
    },
  };
}

export function requestId(value) {
  const normalized = String(value ?? '').trim();
  return /^[a-zA-Z0-9_-]{8,128}$/.test(normalized) ? normalized : randomUUID();
}

function validateTask(task, config, seen) {
  assertObject(task, '搜索任务必须是 JSON 对象');
  rejectUnknown(task, TASK_FIELDS, '搜索任务');
  const taskId = text(task.taskId, 1, 64, 'taskId');
  if (seen.has(taskId)) {
    throw new SearchWrapperError(400, 'DUPLICATE_TASK_ID', 'taskId 不得重复');
  }
  seen.add(taskId);
  const purposeCode = text(task.purposeCode, 1, 64, 'purposeCode');
  if (!/^[A-Z0-9_]+$/.test(purposeCode)) {
    throw new SearchWrapperError(400, 'INVALID_PURPOSE_CODE', 'purposeCode 只能包含大写字母、数字和下划线');
  }
  const mode = String(task.mode ?? 'GENERAL').toUpperCase();
  if (!['GENERAL', 'NEWS'].includes(mode)) {
    throw new SearchWrapperError(400, 'INVALID_MODE', 'mode 只能是 GENERAL 或 NEWS');
  }
  const language = String(task.language ?? 'zh-CN');
  if (!/^[a-z]{2,3}(?:-[A-Z]{2})?$/.test(language)) {
    throw new SearchWrapperError(400, 'INVALID_LANGUAGE', 'language 格式无效');
  }
  return {
    taskId,
    purposeCode,
    mode,
    query: text(task.query, 2, 200, 'query'),
    language,
    freshnessDays: optionalInt(task.freshnessDays, 1, 3650, 'freshnessDays'),
    includeDomains: domains(task.includeDomains),
    excludeDomains: domains(task.excludeDomains),
    maxResults: optionalInt(task.maxResults, 1, config.maxResultsPerTask, 'maxResults')
      ?? config.maxResultsPerTask,
  };
}

function rejectUnknown(value, allowed, scope) {
  const unknown = Object.keys(value).filter(key => !allowed.has(key));
  if (unknown.length > 0) {
    throw new SearchWrapperError(400, 'UNKNOWN_FIELD', `${scope}包含未知字段: ${unknown.join(',')}`);
  }
}

function assertObject(value, message) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new SearchWrapperError(400, 'INVALID_JSON_OBJECT', message);
  }
}

function text(value, min, max, name) {
  const normalized = String(value ?? '').trim();
  if (normalized.length < min || normalized.length > max) {
    throw new SearchWrapperError(400, 'INVALID_FIELD', `${name} 长度必须在 ${min} 到 ${max} 之间`);
  }
  return normalized;
}

function optionalInt(value, min, max, name) {
  if (value == null) return null;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < min || parsed > max) {
    throw new SearchWrapperError(400, 'INVALID_FIELD', `${name} 必须在 ${min} 到 ${max} 之间`);
  }
  return parsed;
}

function domains(value) {
  if (value == null) return [];
  if (!Array.isArray(value) || value.length > 10) {
    throw new SearchWrapperError(400, 'INVALID_DOMAINS', '域名列表必须是最多 10 项的数组');
  }
  return [...new Set(value.map(item => String(item).trim().toLowerCase()))]
    .filter(Boolean)
    .map(domain => {
      if (!/^(?:[a-z0-9-]+\.)+[a-z]{2,}$/i.test(domain)) {
        throw new SearchWrapperError(400, 'INVALID_DOMAIN', `域名格式无效: ${domain}`);
      }
      return domain;
    });
}
