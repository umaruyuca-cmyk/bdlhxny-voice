import { fetchJson, fetchText, tryDataSources, unwrapEastmoneyJsonp } from '../utils/api.js';
import { calculateTechnicalIndicators, round, safeNumber } from '../analysis/technical.js';
import { scoreStock } from '../analysis/scoring.js';
import { evaluateChaseHigh } from '../analysis/chase-high.js';
import { assessDataFreshness, applyFreshnessGuard } from '../analysis/freshness.js';

export async function fetchFundBundle(code, options = {}) {
  const normalized = String(code ?? '').trim();
  const days = options.days ?? 120;
  const [profileResult, historyResult] = await Promise.all([
    fetchFundProfile(normalized, options).catch(() => ({ profile: { code: normalized, name: normalized }, source: 'fallback' })),
    fetchFundHistory(normalized, days, options),
  ]);

  const technical = calculateTechnicalIndicators(historyResult.history, { now: options.now });
  const latest = historyResult.history.at(-1) ?? {};
  const quote = {
    code: normalized,
    name: profileResult.profile.name ?? normalized,
    price: latest.close ?? technical.close,
    changePct: latest.pctChg ?? technical.changePct,
    high: latest.high ?? latest.close,
    low: latest.low ?? latest.close,
  };
  const rawScore = scoreStock(technical, options.analysisProfile ?? options.profile);
  const dataQuality = assessDataFreshness({
    assetKind: 'open_fund',
    assetType: options.assetType ?? options.asset,
    quote,
    history: historyResult.history,
    now: options.now,
  });
  const score = applyFreshnessGuard(rawScore, dataQuality);
  const chase = evaluateChaseHigh({ quote, history: historyResult.history, technical });

  return {
    code: normalized,
    name: quote.name,
    quote,
    history: historyResult.history,
    technical,
    score,
    chase,
    dataQuality,
    sources: {
      quote: profileResult.source,
      history: historyResult.source,
    },
    assetKind: 'open_fund',
  };
}

export async function fetchFundHistory(code, days = 120, options = {}) {
  return tryDataSources([
    { name: '东方财富基金净值', fetch: () => fetchEastmoneyFundNav(code, days) },
  ], { subject: `${code} 场外基金净值`, verbose: options.verbose });
}

async function fetchEastmoneyFundNav(code, days) {
  const data = await fetchJson('https://api.fund.eastmoney.com/f10/lsjz', {
    params: {
      fundCode: code,
      pageIndex: 1,
      pageSize: Math.max(days, 30),
      startDate: '',
      endDate: '',
    },
    headers: {
      Referer: `https://fundf10.eastmoney.com/jjjz_${code}.html`,
    },
  });
  const parsed = typeof data === 'string' ? unwrapEastmoneyJsonp(data) : data;
  const list = parsed?.Data?.LSJZList;
  if (!Array.isArray(list) || list.length === 0) throw new Error('返回空净值列表');

  const rowsDesc = list.map((item) => ({
    date: item.FSRQ,
    close: safeNumber(item.DWJZ),
    high: safeNumber(item.DWJZ),
    low: safeNumber(item.DWJZ),
    open: safeNumber(item.DWJZ),
    pctChg: safeNumber(item.JZZZL),
    volume: 0,
    amount: null,
    turnoverRate: null,
  })).filter((row) => Number.isFinite(row.close));

  const history = rowsDesc.reverse();
  return { history, source: 'eastmoney-fund-nav' };
}

export async function fetchFundProfile(code, options = {}) {
  return tryDataSources([
    { name: '东方财富基金搜索', fetch: () => fetchEastmoneyFundProfile(code) },
  ], { subject: `${code} 基金名称`, verbose: options.verbose });
}

async function fetchEastmoneyFundProfile(code) {
  const text = await fetchText('https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx', {
    params: { m: 1, key: code },
    headers: { Referer: 'https://fund.eastmoney.com/' },
  });
  const parsed = unwrapEastmoneyJsonp(String(text));
  const candidates = parsed?.Datas ?? parsed?.data ?? [];
  const match = Array.isArray(candidates)
    ? candidates.find((item) => String(item.CODE ?? item.code ?? '').trim() === code)
    : null;
  return {
    profile: {
      code,
      name: match?.NAME ?? match?.name ?? code,
      type: match?.FundType ?? match?.type ?? null,
    },
    source: 'eastmoney-fund-search',
  };
}

export function isLikelyOpenFundCode(code, explicitAssetType) {
  const type = String(explicitAssetType ?? '').toLowerCase();
  if (['fund', 'open_fund', 'qdii', 'etf_link'].includes(type)) return true;
  if (['stock', 'etf'].includes(type)) return false;

  const normalized = String(code ?? '').trim();
  // Exchange-traded funds commonly use 15/16/51/56/58 prefixes.
  if (/^(15|16|51|56|58)\d{4}$/.test(normalized)) return false;
  // Common A-share stock prefixes. This avoids treating 600519/000001/300750 as OTC funds.
  if (/^(600|601|603|605|688|689|000|001|002|003|300|301)\d{3}$/.test(normalized)) return false;
  // Other 6-digit fund-like codes, such as 022463/017641/008888/007466, are usually OTC funds.
  return /^\d{6}$/.test(normalized);
}
