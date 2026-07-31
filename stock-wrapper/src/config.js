import path from 'node:path';
import { fileURLToPath } from 'node:url';

const wrapperRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/**
 * 读取 Wrapper 运行配置，集中约束 Skill 路径、超时和并发上限。
 */
export function loadConfig(env = process.env) {
  const skillPath = path.resolve(env.STOCK_SKILL_PATH ?? path.join(wrapperRoot, '..', '..', 'skills', 'stock-analysis-skill'));
  return {
    port: positiveInteger(env.PORT, 3001),
    skillPath,
    cliScript: path.resolve(env.STOCK_SKILL_CLI ?? path.join(skillPath, 'bin', 'stock-analysis.js')),
    nodeBin: env.STOCK_SKILL_NODE ?? process.execPath,
    internalToken: env.INTERNAL_TOKEN ?? '',
    timeoutMs: positiveInteger(env.STOCK_SKILL_TIMEOUT_MS, 120_000),
    maxConcurrency: positiveInteger(env.STOCK_WRAPPER_MAX_CONCURRENCY, 4),
    maxBodyBytes: positiveInteger(env.STOCK_WRAPPER_MAX_BODY_BYTES, 65_536),
    maxOutputBytes: positiveInteger(env.STOCK_WRAPPER_MAX_OUTPUT_BYTES, 10 * 1024 * 1024),
  };
}

function positiveInteger(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}
