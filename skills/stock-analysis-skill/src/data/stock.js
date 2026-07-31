import { fetchJson, fetchText, tryDataSources } from '../utils/api.js';
import { normalizeAStockCode } from '../config.js';
import { calculateTechnicalIndicators, round, safeNumber } from '../analysis/technical.js';
import { scoreStock } from '../analysis/scoring.js';
import { screenFundamentals } from '../analysis/fundamental.js';
import { evaluateChaseHigh } from '../analysis/chase-high.js';
import { fetchFundBundle, isLikelyOpenFundCode } from './fund.js';
import { assessDataFreshness, applyFreshnessGuard } from '../analysis/freshness.js';
import { chinaDateString, chinaDateTimeString, parseEpochSeconds } from '../utils/china-time.js';

const EASTMONEY_QUOTE_FIELDS = [
  'f57', 'f58', 'f43', 'f44', 'f45', 'f46', 'f47', 'f48', 'f50', 'f60',
  'f86', 'f124', 'f169', 'f170', 'f152', 'f162', 'f167', 'f168', 'f116', 'f117', 'f127', 'f128',
].join(',');

const INDEX_MARKETS = new Map([
  ['000001', { eastmoney: '1', tencent: 'sh', suffix: 'SH' }],
  ['000016', { eastmoney: '1', tencent: 'sh', suffix: 'SH' }],
  ['000300', { eastmoney: '1', tencent: 'sh', suffix: 'SH' }],
  ['000688', { eastmoney: '1', tencent: 'sh', suffix: 'SH' }],
  ['000852', { eastmoney: '1', tencent: 'sh', suffix: 'SH' }],
  ['000905', { eastmoney: '1', tencent: 'sh', suffix: 'SH' }],
  ['399001', { eastmoney: '0', tencent: 'sz', suffix: 'SZ' }],
  ['399005', { eastmoney: '0', tencent: 'sz', suffix: 'SZ' }],
  ['399006', { eastmoney: '0', tencent: 'sz', suffix: 'SZ' }],
  ['399673', { eastmoney: '0', tencent: 'sz', suffix: 'SZ' }],
]);

export function isSupportedIndexCode(code) {
  return INDEX_MARKETS.has(normalizeAStockCode(code));
}

export function getMarketPrefix(code, options = {}) {
  const normalized = normalizeAStockCode(code);
  if (options.instrumentType === 'index') {
    const indexMarket = INDEX_MARKETS.get(normalized);
    if (!indexMarket) {
      throw Object.assign(new Error(`暂不支持指数代码 ${normalized}`), {
        code: 'UNSUPPORTED_INDEX_CODE',
      });
    }
    return indexMarket;
  }
  // 上交所：股票 600-609, 688-689, 900 + ETF 510-519, 560-563, 588
  if (/^(600|601|603|605|688|689|900|510|511|512|513|515|516|517|518|560|561|562|563|588)/.test(normalized))
    return { eastmoney: '1', tencent: 'sh', suffix: 'SH' };
  return { eastmoney: '0', tencent: 'sz', suffix: 'SZ' };
}

export function toEastmoneySecid(code, options = {}) {
  const normalized = normalizeAStockCode(code);
  return `${getMarketPrefix(normalized, options).eastmoney}.${normalized}`;
}

export async function fetchStockBundle(code, options = {}) {
  const normalized = normalizeAStockCode(code);
  const days = options.days ?? 120;
  const explicitAssetType = options.assetType ?? options.asset;

  if (isLikelyOpenFundCode(normalized, explicitAssetType)) {
    return fetchFundBundle(normalized, options);
  }

  try {
    const [quoteResult, historyResult] = await Promise.all([
      fetchQuote(normalized, options),
      fetchKlineHistory(normalized, days, options),
    ]);

    const merged = mergeQuoteIntoHistory(historyResult.history, quoteResult.quote);
    // 1. 盘中合成 K 线可能新增一行，最终仍需遵守调用方请求的历史长度。
    const history = merged.history.slice(-Math.max(1, Number.parseInt(days, 10) || 120));
    const technical = calculateTechnicalIndicators(history, { now: options.now });
    // 用量比 API 字段 f50 覆盖自算值（自算是全天量/5日均量，开盘后会严重偏低）
    if (quoteResult.quote.volumeRatio != null) {
      technical.volume.volumeRatio = quoteResult.quote.volumeRatio;
    }
    const quote = {
      ...quoteResult.quote,
      price: quoteResult.quote.price ?? technical.close,
      changePct: quoteResult.quote.changePct ?? technical.changePct,
    };
    const fundamental = screenFundamentals(quote);
    const scored = scoreStock(technical, options.analysisProfile ?? options.profile, fundamental);
    const freshness = assessDataFreshness({
      assetKind: 'exchange_traded',
      assetType: explicitAssetType,
      quote,
      history,
      historyWasSynthesized: merged.synthesized,
      now: options.now,
    });
    const score = applyFreshnessGuard(scored, freshness);
    const chase = evaluateChaseHigh({ quote, history, technical });

    return {
      code: normalized,
      name: quote.name ?? normalized,
      quote,
      history,
      technical,
      score,
      chase,
      fundamental,
      dataQuality: freshness,
      sources: {
        quote: quoteResult.source,
        history: historyResult.source,
      },
      assetKind: 'exchange_traded',
    };
  } catch (error) {
    if (explicitAssetType === 'stock' || explicitAssetType === 'etf') throw error;
    return fetchFundBundle(normalized, options);
  }
}

export async function fetchQuote(code, options = {}) {
  const normalized = normalizeAStockCode(code);
  return tryDataSources([
    { name: '东方财富行情（需校验时间）', fetch: () => fetchEastmoneyQuote(normalized) },
    { name: '新浪行情（需校验时间）', fetch: () => fetchSinaQuote(normalized) },
  ], { subject: `${normalized} 行情数据`, verbose: options.verbose });
}

export async function fetchKlineHistory(code, days = 120, options = {}) {
  const normalized = normalizeAStockCode(code);
  return tryDataSources([
    { name: '东方财富 K 线', fetch: () => fetchEastmoneyKline(normalized, days, options) },
    { name: '腾讯 K 线', fetch: () => fetchTencentKline(normalized, days, options) },
  ], { subject: `${normalized} K线数据`, verbose: options.verbose });
}

async function fetchEastmoneyQuote(code) {
  const fetchedAt = new Date();
  const data = await fetchJson('https://push2.eastmoney.com/api/qt/stock/get', {
    params: {
      secid: toEastmoneySecid(code),
      fields: EASTMONEY_QUOTE_FIELDS,
      fltt: 2,
      invt: 2,
      ut: 'fa5fd1943c7b386f172d6893dbfba10b',
    },
  });
  if (!data?.data) throw new Error('返回空数据');
  const item = data.data;
  const quoteTime = parseEpochSeconds(item.f86) ?? parseEpochSeconds(item.f124);
  return {
    quote: {
      code,
      name: item.f58,
      price: safeNumber(item.f43),
      high: safeNumber(item.f44),
      low: safeNumber(item.f45),
      open: safeNumber(item.f46),
      volume: safeNumber(item.f47),
      amount: safeNumber(item.f48),
      volumeRatio: safeNumber(item.f50),
      preClose: safeNumber(item.f60),
      changeAmount: safeNumber(item.f169),
      changePct: safeNumber(item.f170),
      peRatio: safeNumber(item.f162),
      pbRatio: safeNumber(item.f167),
      turnoverRate: safeNumber(item.f168),
      totalMarketValue: safeNumber(item.f116),
      circulatingMarketValue: safeNumber(item.f117),
      sector: item.f128 || null,
      quoteTime: quoteTime?.toISOString() ?? null,
      tradeDate: quoteTime ? chinaDateString(quoteTime) : null,
      fetchedAt: fetchedAt.toISOString(),
    },
    source: 'eastmoney',
  };
}

async function fetchSinaQuote(code) {
  const fetchedAt = new Date();
  const prefix = getMarketPrefix(code).tencent;
  const text = await fetchText(`https://hq.sinajs.cn/list=${prefix}${code}`, {
    responseType: 'arraybuffer',
    encoding: 'gb18030',
    headers: {
      Referer: 'https://finance.sina.com.cn/',
    },
  });
  const match = String(text).match(/="([^"]*)"/);
  if (!match || !match[1]) throw new Error('返回空数据');
  const parts = match[1].split(',');
  if (parts.length < 32) throw new Error('字段不足');
  const price = safeNumber(parts[3]);
  const preClose = safeNumber(parts[2]);
  const quoteTime = parts[30] && parts[31] ? new Date(`${parts[30]}T${parts[31]}+08:00`) : null;
  const validQuoteTime = quoteTime && !Number.isNaN(quoteTime.getTime()) ? quoteTime : null;
  return {
    quote: {
      code,
      name: parts[0],
      open: safeNumber(parts[1]),
      preClose,
      price,
      high: safeNumber(parts[4]),
      low: safeNumber(parts[5]),
      // 新浪现货行情成交量单位为“股”，日K接口通常为“手”；统一为手后再计算量比。
      volume: normalizeSinaVolume(parts[8]),
      amount: safeNumber(parts[9]),
      changeAmount: price != null && preClose ? round(price - preClose, 2) : null,
      changePct: price != null && preClose ? round((price - preClose) / preClose * 100, 2) : null,
      quoteTime: validQuoteTime?.toISOString() ?? null,
      tradeDate: parts[30] || null,
      fetchedAt: fetchedAt.toISOString(),
    },
    source: 'sina',
  };
}

export function normalizeSinaVolume(value) {
  const volumeShares = safeNumber(value);
  return volumeShares == null ? null : round(volumeShares / 100, 0);
}

export function mergeQuoteIntoHistory(history, quote = {}) {
  const rows = history.map((row) => ({ ...row }));
  const tradeDate = quote.tradeDate ?? (quote.quoteTime ? chinaDateString(new Date(quote.quoteTime)) : null);
  if (!tradeDate || !Number.isFinite(quote.price)) return { history: rows, synthesized: false };

  const latest = rows.at(-1);
  if (latest?.date > tradeDate) return { history: rows, synthesized: false };

  const mergedRow = {
    ...(latest?.date === tradeDate ? latest : {}),
    date: tradeDate,
    open: quote.open ?? (latest?.date === tradeDate ? latest.open : quote.preClose) ?? quote.price,
    close: quote.price,
    high: quote.high ?? quote.price,
    low: quote.low ?? quote.price,
    volume: quote.volume ?? (latest?.date === tradeDate ? latest.volume : 0),
    amount: quote.amount ?? (latest?.date === tradeDate ? latest.amount : null),
    pctChg: quote.changePct ?? (latest?.date === tradeDate ? latest.pctChg : null),
    turnoverRate: quote.turnoverRate ?? (latest?.date === tradeDate ? latest.turnoverRate : null),
    provisional: true,
  };

  if (latest?.date === tradeDate) rows[rows.length - 1] = mergedRow;
  else rows.push(mergedRow);
  return { history: rows, synthesized: latest?.date !== tradeDate };
}

async function fetchEastmoneyKline(code, days, options = {}) {
  const data = await fetchJson('https://push2his.eastmoney.com/api/qt/stock/kline/get', {
    params: {
      secid: toEastmoneySecid(code, options),
      klt: 101,
      fqt: 1,
      beg: '19900101',
      end: '20500101',
      lmt: days,
      fields1: 'f1,f2,f3,f4,f5,f6',
      fields2: 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
    },
  });
  const klines = data?.data?.klines;
  if (!Array.isArray(klines) || klines.length === 0) throw new Error('返回空 K 线');
  // 1. 东方财富在同时传入起止日期时可能忽略 lmt，需在本地强制保留请求的最近交易日。
  const requestedDays = Math.max(1, Number.parseInt(days, 10) || 120);
  const history = klines.map(parseEastmoneyKline).filter((row) => row.close != null).slice(-requestedDays);
  return {
    history,
    source: 'eastmoney',
  };
}

function parseEastmoneyKline(line) {
  const [date, open, close, high, low, volume, amount, amplitude, pctChg, change, turnover] = String(line).split(',');
  return {
    date,
    open: safeNumber(open),
    close: safeNumber(close),
    high: safeNumber(high),
    low: safeNumber(low),
    volume: safeNumber(volume),
    amount: safeNumber(amount),
    amplitude: safeNumber(amplitude),
    pctChg: safeNumber(pctChg),
    change: safeNumber(change),
    turnoverRate: safeNumber(turnover),
  };
}

async function fetchTencentKline(code, days, options = {}) {
  const prefix = getMarketPrefix(code, options).tencent;
  const symbol = `${prefix}${code}`;
  const data = await fetchJson('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get', {
    params: {
      param: `${symbol},day,,,${days},qfq`,
    },
    headers: {
      Referer: 'https://gu.qq.com/',
    },
  });
  const raw = data?.data?.[symbol];
  const rows = raw?.qfqday ?? raw?.day;
  if (!Array.isArray(rows) || rows.length === 0) throw new Error('返回空 K 线');
  const history = rows.map((row, index) => {
    const [date, open, close, high, low, volume] = row;
    const previous = rows[index - 1]?.[2];
    return {
      date,
      open: safeNumber(open),
      close: safeNumber(close),
      high: safeNumber(high),
      low: safeNumber(low),
      volume: safeNumber(volume),
      amount: null,
      pctChg: previous ? round((safeNumber(close) - safeNumber(previous)) / safeNumber(previous) * 100, 2) : null,
    };
  });
  return { history, source: 'tencent' };
}
