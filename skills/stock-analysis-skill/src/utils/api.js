import axios from 'axios';
import { Agent as HttpAgent } from 'node:http';
import { Agent as HttpsAgent } from 'node:https';
import { DEFAULTS } from '../config.js';
import { logSourceFailure } from './logger.js';

const sharedHttpAgent = new HttpAgent({
  keepAlive: true,
  maxSockets: DEFAULTS.maxHttpConcurrency,
  scheduling: 'lifo',
});
const sharedHttpsAgent = new HttpsAgent({
  keepAlive: true,
  maxSockets: DEFAULTS.maxHttpConcurrency,
  scheduling: 'lifo',
});

export const http = axios.create({
  timeout: DEFAULTS.requestTimeoutMs,
  httpAgent: sharedHttpAgent,
  httpsAgent: sharedHttpsAgent,
  headers: {
    Accept: '*/*',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36',
    Referer: 'https://finance.eastmoney.com/',
  },
});

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * 判断错误是否适合自动重试，避免对参数错误和明确拒绝持续施压。
 */
export function isRetryableRequestError(error) {
  const status = Number(error?.response?.status);
  if ([408, 425, 429, 500, 502, 503, 504].includes(status)) return true;
  if (Number.isFinite(status) && status > 0) return false;
  return new Set([
    'ECONNABORTED',
    'ECONNRESET',
    'ETIMEDOUT',
    'EAI_AGAIN',
    'ENETUNREACH',
    'EHOSTUNREACH',
  ]).has(error?.code);
}

/**
 * 计算带随机抖动的退避时间，降低多个 CLI 进程同时重试造成的请求尖峰。
 */
export function retryDelayMs(attempt, error, random = Math.random) {
  const retryAfter = Number(error?.response?.headers?.['retry-after']);
  if (Number.isFinite(retryAfter) && retryAfter > 0) {
    return Math.min(retryAfter * 1000, 10_000);
  }
  const exponential = Math.min(500 * 2 ** Math.max(0, attempt - 1), 5_000);
  return Math.round(exponential + exponential * 0.25 * random());
}

export async function requestWithRetry(config, options = {}) {
  const retries = options.retries ?? DEFAULTS.retries;
  let lastError;

  for (let attempt = 1; attempt <= retries; attempt += 1) {
    try {
      return await http.request(config);
    } catch (error) {
      lastError = error;
      if (attempt < retries && isRetryableRequestError(error)) {
        await sleep(retryDelayMs(attempt, error, options.random));
        continue;
      }
      throw error;
    }
  }

  throw lastError;
}

export async function fetchJson(url, options = {}) {
  const response = await requestWithRetry({
    url,
    method: 'GET',
    params: options.params,
    responseType: 'json',
    timeout: options.timeout ?? DEFAULTS.requestTimeoutMs,
    headers: options.headers,
  }, options);
  return response.data;
}

export async function fetchText(url, options = {}) {
  const response = await requestWithRetry({
    url,
    method: 'GET',
    params: options.params,
    responseType: options.responseType ?? 'text',
    timeout: options.timeout ?? DEFAULTS.requestTimeoutMs,
    headers: options.headers,
  }, options);

  if (options.encoding && response.data instanceof ArrayBuffer) {
    return new TextDecoder(options.encoding).decode(response.data);
  }
  if (Buffer.isBuffer(response.data) && options.encoding) {
    return new TextDecoder(options.encoding).decode(response.data);
  }
  return response.data;
}

export async function tryDataSources(sources, context = {}) {
  const errors = [];
  for (const source of sources) {
    try {
      const result = await source.fetch();
      if (result == null) {
        throw new Error('返回空数据');
      }
      return { ...result, source: result.source ?? source.name };
    } catch (error) {
      errors.push(`${source.name}: ${error.message}`);
      logSourceFailure(source.name, error, context.verbose);
    }
  }

  const subject = context.subject ?? '数据';
  throw new Error(`无法获取 ${subject}: 已尝试 ${sources.length} 个数据源 (${errors.join('; ')})`);
}

export function unwrapEastmoneyJsonp(payload) {
  if (typeof payload !== 'string') {
    return payload;
  }
  const match = payload.match(/^[^(]*\((.*)\);?$/s);
  return JSON.parse(match ? match[1] : payload);
}
