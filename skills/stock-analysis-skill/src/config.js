import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { getAnalysisProfile, isAnalysisProfile } from './analysis/profiles.js';
import { normalizeTradingCosts } from './analysis/trading.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..');

export const DEFAULTS = {
  requestTimeoutMs: 10000,
  retries: 3,
  maxHttpConcurrency: 6,
  portfolioFetchConcurrency: 2,
  quantFetchConcurrency: 2,
  sectorHistoryConcurrency: 3,
  monthlyCashReserveRatio: 0.2,
  days: 120,
};

export function resolveProjectPath(...parts) {
  return path.join(projectRoot, ...parts);
}

export function loadPortfolio(configPath = 'portfolio.json', overrides = {}) {
  const requestedPath = path.resolve(process.cwd(), configPath);
  const fallbackPath = resolveProjectPath('templates', 'portfolio.example.json');
  const requestedExists = fs.existsSync(requestedPath);
  if (!requestedExists && overrides.allowFallback === false) {
    throw Object.assign(new Error('真实持仓配置文件不存在'), {
      code: 'PORTFOLIO_CONFIG_NOT_FOUND',
    });
  }
  const filePath = requestedExists ? requestedPath : fallbackPath;
  const usedFallback = !requestedExists;

  let raw;
  try {
    raw = fs.readFileSync(filePath, 'utf8');
  } catch (error) {
    throw new Error(`无法读取配置文件 ${filePath}: ${error.message}`);
  }

  let portfolio;
  try {
    portfolio = JSON.parse(raw);
  } catch (error) {
    throw new Error(`portfolio.json 不是有效 JSON: ${error.message}`);
  }

  const validation = validatePortfolio(portfolio);
  if (overrides.requirePositions === true && portfolio.positions?.length === 0) {
    validation.errors.push('positions 至少需要一条真实持仓');
  }
  if (validation.errors.length > 0) {
    throw new Error(`portfolio.json 校验失败:\n${validation.errors.map((item) => `- ${item}`).join('\n')}`);
  }

  return {
    ...portfolio,
    analysisProfile: getAnalysisProfile().key,
    cash: Number(portfolio.cash ?? 0),
    tradingCosts: normalizeTradingCosts(portfolio.tradingCosts),
    positions: portfolio.positions.map((position) => ({
      ...position,
      code: normalizeAStockCode(position.code),
      avgCost: Number(position.avgCost),
      shares: Number(position.shares),
      availableShares: position.availableShares == null ? null : Number(position.availableShares),
      targetWeight: Number(position.targetWeight),
      sector: position.sector ?? '未分类',
      assetType: position.assetType ?? 'auto',
      riskRole: position.riskRole ?? null,
      maxWeight: position.maxWeight == null ? null : Number(position.maxWeight),
    })),
    __meta: {
      filePath,
      usedFallback,
      warnings: validation.warnings,
      tushareTokenConfigured: Boolean(process.env.TUSHARE_TOKEN),
    },
  };
}

export function validatePortfolio(portfolio) {
  const errors = [];
  const warnings = [];

  if (!portfolio || typeof portfolio !== 'object' || Array.isArray(portfolio)) {
    return { errors: ['根节点必须是对象'], warnings };
  }

  if (!Number.isFinite(Number(portfolio.monthlyBudget)) || Number(portfolio.monthlyBudget) <= 0) {
    errors.push('monthlyBudget 必须是大于 0 的数字');
  }

  if (portfolio.analysisProfile != null) {
    warnings.push('analysisProfile 已停用（统一为客观标准），该字段将被忽略，可从配置中删除');
  }

  if (portfolio.tradingCosts != null && typeof portfolio.tradingCosts !== 'object') {
    errors.push('tradingCosts must be an object');
  }

  if (!Array.isArray(portfolio.positions)) {
    errors.push('positions 必须是数组');
    return { errors, warnings };
  }

  if (portfolio.positions.length === 0) {
    warnings.push('positions 为空，将只输出市场和板块概况');
  }

  let targetWeightSum = 0;
  portfolio.positions.forEach((position, index) => {
    const prefix = `positions[${index}]`;
    if (!isAStockCode(position.code)) {
      errors.push(`${prefix}.code 必须是 6 位 A 股代码，例如 600519`);
    }
    if (!position.name || typeof position.name !== 'string') {
      errors.push(`${prefix}.name 必须是股票名称`);
    }
    if (!Number.isFinite(Number(position.avgCost)) || Number(position.avgCost) <= 0) {
      errors.push(`${prefix}.avgCost 必须是大于 0 的数字`);
    }
    if (!Number.isFinite(Number(position.shares)) || Number(position.shares) <= 0) {
      errors.push(`${prefix}.shares 必须是大于 0 的数字`);
    }
    if (!position.buyDate || Number.isNaN(Date.parse(position.buyDate))) {
      errors.push(`${prefix}.buyDate 必须是有效日期，例如 2025-12-01`);
    }
    if (!Number.isFinite(Number(position.targetWeight)) || Number(position.targetWeight) < 0 || Number(position.targetWeight) > 1) {
      errors.push(`${prefix}.targetWeight 必须在 0 到 1 之间`);
    } else {
      targetWeightSum += Number(position.targetWeight);
    }
    if (position.maxWeight != null && (!Number.isFinite(Number(position.maxWeight)) || Number(position.maxWeight) <= 0 || Number(position.maxWeight) > 1)) {
      errors.push(`${prefix}.maxWeight 必须在 0 到 1 之间`);
    }
    if (position.availableShares != null && (!Number.isFinite(Number(position.availableShares)) || Number(position.availableShares) < 0)) {
      errors.push(`${prefix}.availableShares must be >= 0`);
    }
  });

  if (targetWeightSum > 1.01) {
    warnings.push(`targetWeight 合计 ${(targetWeightSum * 100).toFixed(1)}%，超过 100%，月度分配会按比例压缩`);
  }

  return { errors, warnings };
}

export function isAStockCode(code) {
  return /^\d{6}$/.test(String(code ?? '').trim().replace(/^(SH|SZ)/i, '').replace(/\.(SH|SZ)$/i, ''));
}

export function normalizeAStockCode(code) {
  return String(code ?? '').trim().toUpperCase().replace(/^(SH|SZ)/, '').replace(/\.(SH|SZ)$/, '');
}
