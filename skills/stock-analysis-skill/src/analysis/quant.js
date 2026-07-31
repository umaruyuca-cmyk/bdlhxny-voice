import { movingAverage, round } from './technical.js';

export const DEFAULT_QUANT_CONFIG = Object.freeze({
  lookbacks: [20, 60, 120],
  momentumWeights: [0.4, 0.35, 0.25],
  trendMaPeriod: 60,
  volatilityPeriod: 20,
  regimeMaPeriod: 200,
  regimeVolatilityLookback: 252,
  regimeMaxVolatilityPercentile: 0.8,
  targetAnnualVolatility: 0.12,
  maxAssetWeight: 0.35,
  selectCount: 3,
  rebalanceEvery: 5,
  annualTradingDays: 252,
  transactionCostRate: 0.0003,
});

export function validateQuantConfig(config = {}) {
  const settings = { ...DEFAULT_QUANT_CONFIG, ...config };
  const positiveIntegers = ['trendMaPeriod', 'volatilityPeriod', 'regimeMaPeriod', 'selectCount', 'rebalanceEvery'];
  positiveIntegers.forEach((key) => {
    if (!Number.isInteger(settings[key]) || settings[key] < 1) throw new Error(`${key} 必须是正整数`);
  });
  if (!Array.isArray(settings.lookbacks) || settings.lookbacks.length === 0
    || settings.lookbacks.some((value) => !Number.isInteger(value) || value < 1)) {
    throw new Error('lookbacks 必须是非空正整数数组');
  }
  if (!Array.isArray(settings.momentumWeights)
    || settings.momentumWeights.length !== settings.lookbacks.length
    || settings.momentumWeights.some((value) => !Number.isFinite(value) || value < 0)) {
    throw new Error('momentumWeights 必须与 lookbacks 等长且均为非负数');
  }
  if (!(settings.maxAssetWeight > 0 && settings.maxAssetWeight <= 1)) {
    throw new Error('maxAssetWeight 必须在 (0, 1] 范围内');
  }
  if (!(settings.targetAnnualVolatility > 0 && settings.targetAnnualVolatility <= 1)) {
    throw new Error('targetAnnualVolatility 必须在 (0, 1] 范围内');
  }
  if (!(settings.transactionCostRate >= 0 && settings.transactionCostRate <= 0.1)) {
    throw new Error('transactionCostRate 必须在 [0, 0.1] 范围内');
  }
  if (!(settings.regimeMaxVolatilityPercentile > 0 && settings.regimeMaxVolatilityPercentile <= 1)) {
    throw new Error('regimeMaxVolatilityPercentile 必须在 (0, 1] 范围内');
  }
  return settings;
}

function finiteRows(history) {
  return history
    .filter((row) => row?.date && Number.isFinite(row.close) && row.close > 0)
    .map((row) => ({ ...row }))
    .sort((a, b) => String(a.date).localeCompare(String(b.date)));
}

function mean(values) {
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function sampleStd(values) {
  if (values.length < 2) return null;
  const average = mean(values);
  const variance = values.reduce((sum, value) => sum + (value - average) ** 2, 0) / (values.length - 1);
  return Math.sqrt(variance);
}

export function calculateMomentum(history, lookback) {
  const rows = finiteRows(history);
  if (!Number.isInteger(lookback) || lookback < 1 || rows.length <= lookback) return null;
  const latest = rows.at(-1).close;
  const base = rows.at(-(lookback + 1)).close;
  return base > 0 ? latest / base - 1 : null;
}

export function calculateAnnualizedVolatility(history, period = 20, annualTradingDays = 252) {
  const rows = finiteRows(history);
  if (rows.length <= period) return null;
  const closes = rows.slice(-(period + 1)).map((row) => row.close);
  const returns = closes.slice(1).map((close, index) => Math.log(close / closes[index]));
  const dailyVolatility = sampleStd(returns);
  return dailyVolatility == null ? null : dailyVolatility * Math.sqrt(annualTradingDays);
}

export function calculateQuantFeatures(history, config = {}) {
  const settings = { ...DEFAULT_QUANT_CONFIG, ...config };
  const rows = finiteRows(history);
  const closes = rows.map((row) => row.close);
  const latest = rows.at(-1);
  const trendMa = movingAverage(closes, settings.trendMaPeriod).at(-1) ?? null;
  const momentum = Object.fromEntries(
    settings.lookbacks.map((lookback) => [lookback, calculateMomentum(rows, lookback)]),
  );
  const volatility = calculateAnnualizedVolatility(
    rows,
    settings.volatilityPeriod,
    settings.annualTradingDays,
  );
  const complete = latest != null
    && trendMa != null
    && volatility != null
    && settings.lookbacks.every((lookback) => momentum[lookback] != null);

  return {
    asOf: latest?.date ?? null,
    close: latest?.close ?? null,
    momentum,
    trendMa,
    trendEligible: complete && latest.close > trendMa,
    annualizedVolatility: volatility,
    complete,
  };
}

export function zScores(values) {
  const valid = values.filter(Number.isFinite);
  if (valid.length === 0) return values.map(() => null);
  const average = mean(valid);
  const deviation = sampleStd(valid);
  if (deviation == null || deviation === 0) {
    return values.map((value) => (Number.isFinite(value) ? 0 : null));
  }
  return values.map((value) => (Number.isFinite(value) ? (value - average) / deviation : null));
}

export function rankMomentumUniverse(assets, config = {}) {
  const settings = { ...DEFAULT_QUANT_CONFIG, ...config };
  const evaluated = assets.map((asset) => ({
    code: asset.code,
    name: asset.name ?? asset.code,
    features: calculateQuantFeatures(asset.history, settings),
  }));

  const zByLookback = Object.fromEntries(settings.lookbacks.map((lookback) => [
    lookback,
    zScores(evaluated.map((asset) => asset.features.momentum[lookback])),
  ]));

  return evaluated.map((asset, index) => {
    const scoreParts = settings.lookbacks.map((lookback, weightIndex) => {
      const z = zByLookback[lookback][index];
      return z == null ? null : z * settings.momentumWeights[weightIndex];
    });
    const score = scoreParts.every(Number.isFinite)
      ? scoreParts.reduce((sum, value) => sum + value, 0)
      : null;
    return { ...asset, score };
  }).sort((a, b) => (b.score ?? -Infinity) - (a.score ?? -Infinity));
}

export function allocateInverseVolatility(rankedAssets, config = {}) {
  const settings = { ...DEFAULT_QUANT_CONFIG, ...config };
  const selected = rankedAssets
    .filter((asset) => asset.features.complete && asset.features.trendEligible && Number.isFinite(asset.score))
    .slice(0, settings.selectCount);
  if (selected.length === 0) return { weights: {}, cashWeight: 1, estimatedVolatility: 0 };

  const inverseVolatility = selected.map((asset) => 1 / asset.features.annualizedVolatility);
  const inverseSum = inverseVolatility.reduce((sum, value) => sum + value, 0);
  let baseWeights = inverseVolatility.map((value) => value / inverseSum);

  // Iterative cap redistribution keeps every position below the configured hard limit.
  for (let pass = 0; pass < selected.length; pass += 1) {
    const capped = baseWeights.map((weight) => Math.min(weight, settings.maxAssetWeight));
    const remaining = 1 - capped.reduce((sum, value) => sum + value, 0);
    const uncapped = baseWeights.map((weight, index) => (capped[index] < settings.maxAssetWeight ? weight : 0));
    const uncappedSum = uncapped.reduce((sum, value) => sum + value, 0);
    baseWeights = capped.map((weight, index) => (
      uncappedSum > 0 ? weight + remaining * uncapped[index] / uncappedSum : weight
    ));
  }

  const estimatedVolatility = Math.sqrt(selected.reduce(
    (sum, asset, index) => sum + (baseWeights[index] * asset.features.annualizedVolatility) ** 2,
    0,
  ));
  const exposureScale = estimatedVolatility > 0
    ? Math.min(1, settings.targetAnnualVolatility / estimatedVolatility)
    : 0;
  const weights = Object.fromEntries(selected.map((asset, index) => [
    asset.code,
    baseWeights[index] * exposureScale,
  ]));
  const invested = Object.values(weights).reduce((sum, value) => sum + value, 0);
  return {
    weights,
    cashWeight: Math.max(0, 1 - invested),
    estimatedVolatility: estimatedVolatility * exposureScale,
  };
}

export function evaluateMarketRegime(history, config = {}) {
  const settings = { ...DEFAULT_QUANT_CONFIG, ...config };
  const rows = finiteRows(history);
  const closes = rows.map((row) => row.close);
  const regimeMa = movingAverage(closes, settings.regimeMaPeriod).at(-1) ?? null;
  const currentVolatility = calculateAnnualizedVolatility(
    rows,
    settings.volatilityPeriod,
    settings.annualTradingDays,
  );
  const volatilitySamples = [];
  const sampleStart = Math.max(
    settings.volatilityPeriod + 1,
    rows.length - settings.regimeVolatilityLookback,
  );
  for (let end = sampleStart; end <= rows.length; end += 1) {
    const volatility = calculateAnnualizedVolatility(
      rows.slice(0, end),
      settings.volatilityPeriod,
      settings.annualTradingDays,
    );
    if (Number.isFinite(volatility)) volatilitySamples.push(volatility);
  }
  const volatilityPercentile = currentVolatility == null || volatilitySamples.length === 0
    ? null
    : volatilitySamples.filter((value) => value <= currentVolatility).length / volatilitySamples.length;
  const complete = rows.length >= settings.regimeMaPeriod
    && regimeMa != null
    && currentVolatility != null
    && volatilityPercentile != null;
  return {
    asOf: rows.at(-1)?.date ?? null,
    close: rows.at(-1)?.close ?? null,
    ma: regimeMa,
    annualizedVolatility: currentVolatility,
    volatilityPercentile,
    eligible: complete
      && rows.at(-1).close > regimeMa
      && volatilityPercentile <= settings.regimeMaxVolatilityPercentile,
    complete,
  };
}

function commonDates(assets) {
  if (assets.length === 0) return [];
  const sets = assets.map((asset) => new Set(finiteRows(asset.history).map((row) => row.date)));
  return [...sets[0]].filter((date) => sets.every((set) => set.has(date))).sort();
}

function maxDrawdown(equityCurve) {
  let peak = -Infinity;
  let worst = 0;
  equityCurve.forEach(({ equity }) => {
    peak = Math.max(peak, equity);
    worst = Math.min(worst, equity / peak - 1);
  });
  return worst;
}

function summarizeReturns(dailyReturns, equityCurve, annualTradingDays) {
  const equity = equityCurve.at(-1)?.equity ?? 1;
  const years = dailyReturns.length / annualTradingDays;
  const cagr = years > 0 ? equity ** (1 / years) - 1 : 0;
  const dailyStd = sampleStd(dailyReturns) ?? 0;
  const annualizedVolatility = dailyStd * Math.sqrt(annualTradingDays);
  const sharpe = dailyStd > 0
    ? mean(dailyReturns) / dailyStd * Math.sqrt(annualTradingDays)
    : 0;
  const drawdown = maxDrawdown(equityCurve);
  return {
    finalEquity: round(equity, 6),
    totalReturn: round(equity - 1, 6),
    cagr: round(cagr, 6),
    annualizedVolatility: round(annualizedVolatility, 6),
    sharpe: round(sharpe, 4),
    maxDrawdown: round(drawdown, 6),
    calmar: drawdown < 0 ? round(cagr / Math.abs(drawdown), 4) : null,
  };
}

function benchmarkPerformance(benchmark, startDate, endDate, annualTradingDays) {
  if (!benchmark) return null;
  const rows = finiteRows(benchmark.history).filter((row) => row.date >= startDate && row.date <= endDate);
  if (rows.length < 2) return null;
  let equity = 1;
  const dailyReturns = [];
  const equityCurve = [{ date: rows[0].date, equity }];
  for (let index = 1; index < rows.length; index += 1) {
    const dailyReturn = rows[index].close / rows[index - 1].close - 1;
    dailyReturns.push(dailyReturn);
    equity *= 1 + dailyReturn;
    equityCurve.push({ date: rows[index].date, equity });
  }
  return summarizeReturns(dailyReturns, equityCurve, annualTradingDays);
}

export function backtestMomentumRotation(assets, config = {}, benchmark = null) {
  const settings = validateQuantConfig(config);
  if (!Array.isArray(assets) || assets.length < 1) throw new Error('至少需要一个可回测资产');
  if (new Set(assets.map((asset) => asset.code)).size !== assets.length) throw new Error('ETF代码不能重复');
  const normalized = assets.map((asset) => ({ ...asset, history: finiteRows(asset.history) }));
  const dates = commonDates(normalized);
  const minimumHistory = Math.max(...settings.lookbacks, settings.trendMaPeriod, settings.volatilityPeriod) + 1;
  if (dates.length <= minimumHistory) {
    throw new Error(`回测至少需要 ${minimumHistory + 1} 个共同交易日，当前只有 ${dates.length} 个`);
  }

  const rowsByCode = Object.fromEntries(normalized.map((asset) => [
    asset.code,
    new Map(asset.history.map((row) => [row.date, row])),
  ]));
  let equity = 1;
  let weights = {};
  let totalTurnover = 0;
  let totalCosts = 0;
  const dailyReturns = [];
  const equityCurve = [{ date: dates[minimumHistory - 1], equity }];
  const rebalances = [];

  for (let dateIndex = minimumHistory; dateIndex < dates.length; dateIndex += 1) {
    const date = dates[dateIndex];
    const previousDate = dates[dateIndex - 1];
    if ((dateIndex - minimumHistory) % settings.rebalanceEvery === 0) {
      const signalAssets = normalized.map((asset) => ({
        code: asset.code,
        name: asset.name,
        history: dates.slice(0, dateIndex).map((signalDate) => rowsByCode[asset.code].get(signalDate)),
      }));
      const ranked = rankMomentumUniverse(signalAssets, settings);
      const benchmarkHistory = benchmark
        ? dates.slice(0, dateIndex).map((signalDate) => (
          benchmark.history.find((row) => row.date === signalDate)
        )).filter(Boolean)
        : null;
      const regime = benchmarkHistory ? evaluateMarketRegime(benchmarkHistory, settings) : null;
      const allocation = regime && !regime.eligible
        ? { weights: {}, cashWeight: 1, estimatedVolatility: 0 }
        : allocateInverseVolatility(ranked, settings);
      const allCodes = new Set([...Object.keys(weights), ...Object.keys(allocation.weights)]);
      const turnover = [...allCodes].reduce(
        (sum, code) => sum + Math.abs((allocation.weights[code] ?? 0) - (weights[code] ?? 0)),
        0,
      );
      const cost = turnover * settings.transactionCostRate;
      equity *= 1 - cost;
      totalTurnover += turnover;
      totalCosts += cost;
      weights = allocation.weights;
      rebalances.push({
        signalDate: previousDate,
        effectiveDate: date,
        weights: { ...weights },
        cashWeight: allocation.cashWeight,
        turnover,
        cost,
        regime,
      });
    }

    const portfolioReturn = Object.entries(weights).reduce((sum, [code, weight]) => {
      const previousClose = rowsByCode[code].get(previousDate)?.close;
      const close = rowsByCode[code].get(date)?.close;
      return Number.isFinite(previousClose) && Number.isFinite(close)
        ? sum + weight * (close / previousClose - 1)
        : sum;
    }, 0);
    equity *= 1 + portfolioReturn;
    dailyReturns.push(portfolioReturn);
    equityCurve.push({ date, equity });
  }

  const performance = summarizeReturns(dailyReturns, equityCurve, settings.annualTradingDays);
  const period = { start: equityCurve[0].date, end: equityCurve.at(-1).date, tradingDays: dailyReturns.length };

  return {
    config: settings,
    period,
    metrics: {
      ...performance,
      totalTurnover: round(totalTurnover, 4),
      estimatedCostDrag: round(totalCosts, 6),
    },
    benchmarkMetrics: benchmarkPerformance(
      benchmark,
      period.start,
      period.end,
      settings.annualTradingDays,
    ),
    currentRanking: rankMomentumUniverse(normalized, settings),
    currentRegime: benchmark ? evaluateMarketRegime(benchmark.history, settings) : null,
    currentAllocation: (() => {
      const ranking = rankMomentumUniverse(normalized, settings);
      const regime = benchmark ? evaluateMarketRegime(benchmark.history, settings) : null;
      return regime && !regime.eligible
        ? { weights: {}, cashWeight: 1, estimatedVolatility: 0 }
        : allocateInverseVolatility(ranking, settings);
    })(),
    rebalances,
    equityCurve,
  };
}
