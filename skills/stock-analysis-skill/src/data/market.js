import { fetchJson, tryDataSources } from '../utils/api.js';
import { round, safeNumber } from '../analysis/technical.js';
import { chinaDateString, chinaDateTimeString, parseEpochSeconds } from '../utils/china-time.js';

const INDEXES = [
  { name: '上证指数', secid: '1.000001' },
  { name: '深证成指', secid: '0.399001' },
  { name: '创业板指', secid: '0.399006' },
];

export async function fetchMarketOverview(options = {}) {
  const [indexes, northbound] = await Promise.all([
    fetchIndexQuotes(options).catch(() => []),
    fetchNorthboundFlow(options).catch(() => null),
  ]);

  const quoteTimes = indexes.map((item) => item.quoteTime).filter(Boolean).sort();
  return {
    indexes,
    northbound,
    dataTime: quoteTimes.length ? chinaDateTimeString(new Date(quoteTimes.at(-1))) : null,
  };
}

export async function fetchIndexQuotes(options = {}) {
  return Promise.all(INDEXES.map(async (index) => {
    const result = await tryDataSources([
      { name: '东方财富指数行情', fetch: () => fetchEastmoneyIndex(index) },
    ], { subject: index.name, verbose: options.verbose });
    return result.quote;
  }));
}

async function fetchEastmoneyIndex(index) {
  const data = await fetchJson('https://push2.eastmoney.com/api/qt/stock/get', {
    params: {
      secid: index.secid,
      fields: 'f58,f43,f86,f124,f169,f170,f44,f45,f46,f60',
      fltt: 2,
      invt: 2,
    },
  });
  if (!data?.data) throw new Error('返回空数据');
  const quoteTime = parseEpochSeconds(data.data.f86) ?? parseEpochSeconds(data.data.f124);
  return {
    quote: {
      name: data.data.f58 ?? index.name,
      price: safeNumber(data.data.f43),
      changeAmount: safeNumber(data.data.f169),
      changePct: safeNumber(data.data.f170),
      high: safeNumber(data.data.f44),
      low: safeNumber(data.data.f45),
      open: safeNumber(data.data.f46),
      preClose: safeNumber(data.data.f60),
      quoteTime: quoteTime?.toISOString() ?? null,
      tradeDate: quoteTime ? chinaDateString(quoteTime) : null,
    },
    source: 'eastmoney',
  };
}

export async function fetchNorthboundFlow(options = {}) {
  return tryDataSources([
    { name: '东方财富北向资金', fetch: fetchEastmoneyNorthbound },
  ], { subject: '北向资金', verbose: options.verbose });
}

async function fetchEastmoneyNorthbound() {
  const data = await fetchJson('https://push2.eastmoney.com/api/qt/kamt/get', {
    params: {
      fields1: 'f1,f2,f3,f4',
      fields2: 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60',
      ut: 'b2884a393a59ad64002292a3e90d46a5',
    },
  });
  const source = data?.data;
  if (!source) throw new Error('返回空数据');
  const hk2sh = safeNumber(source.hk2sh?.dayNetAmtIn);
  const hk2sz = safeNumber(source.hk2sz?.dayNetAmtIn);
  const total = [hk2sh, hk2sz].filter(Number.isFinite).reduce((sum, value) => sum + value, 0);
  return {
    northbound: {
      hk2sh: hk2sh == null ? null : round(hk2sh / 10000, 2),
      hk2sz: hk2sz == null ? null : round(hk2sz / 10000, 2),
      total: total ? round(total / 10000, 2) : null,
      unit: '亿元',
    },
    source: 'eastmoney',
  };
}
