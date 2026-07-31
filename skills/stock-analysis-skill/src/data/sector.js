import { fetchJson } from '../utils/api.js';
import { round, safeNumber } from '../analysis/technical.js';
import { chinaDateString, chinaDateTimeString, parseEpochSeconds } from '../utils/china-time.js';
import { DEFAULTS } from '../config.js';
import { mapWithConcurrency } from '../utils/concurrency.js';

const SECTOR_FIELDS = [
  'f12', 'f14', 'f2', 'f3', 'f8', 'f62', 'f66', 'f69', 'f72', 'f75',
  'f104', 'f105', 'f106', 'f109', 'f124', 'f128', 'f136',
].join(',');

const HEAT_FORMULA_VERSION = 'sector-heat-v2';
const HEAT_NORMALIZATION = 'cross_sectional_percentile';
const HEAT_COMPONENTS = Object.freeze({
  daily: { field: 'changePct', weight: 0.35 },
  fiveDay: { field: 'change5d', weight: 0.25 },
  twentyDay: { field: 'change20d', weight: 0.15 },
  fundFlow: { field: 'mainNetInflow', weight: 0.15 },
  turnover: { field: 'turnoverRate', weight: 0.10 },
});

export async function fetchRankedSectors(options = {}) {
  const type = options.type === 'concept' ? 'concept' : 'industry';
  const limit = options.limit ?? 20;
  const rows = await fetchEastmoneySectors(type, Math.max(limit, 30));
  // 1. 列表接口只可靠提供当日和 5 日涨跌，先用列表字段初筛，再受控复核候选板块 K 线。
  const defaultEnrichmentLimit = Math.min(Math.max(limit, 5), 10);
  const enrichmentLimit = Math.max(0, Math.min(
    options.historyEnrichmentLimit == null
      ? defaultEnrichmentLimit
      : Number.parseInt(options.historyEnrichmentLimit, 10) || 0,
    rows.length,
  ));
  const preliminary = rankSectorHeat(rows);
  const candidates = [...preliminary]
    .sort((a, b) => b.heatScore - a.heatScore)
    .slice(0, enrichmentLimit);
  const stats = await mapWithConcurrency(
    candidates,
    DEFAULTS.sectorHistoryConcurrency,
    async (sector) => {
      try {
        return {
          code: sector.code,
          stats: await fetchSectorKlineStats(sector.code),
        };
      } catch {
        return null;
      }
    },
  );
  const statsByCode = new Map(
    stats.filter(Boolean).map((item) => [item.code, item.stats]),
  );
  const withHistory = rows.map((sector) => {
    const historyStats = statsByCode.get(sector.code);
    return historyStats
      ? { ...sector, ...historyStats, historyVerified: true }
      : { ...sector, historyVerified: false };
  });
  const enriched = rankSectorHeat(withHistory.map((sector) => ({
    ...sector,
    rotation: detectSectorRotation(sector),
  })));

  const ranked = enriched
    .sort((a, b) => b.heatScore - a.heatScore)
    .slice(0, limit);
  const verifiedRankedCount = ranked.filter((sector) => sector.historyVerified).length;

  const leaders = [...enriched].sort((a, b) => (b.changePct ?? -999) - (a.changePct ?? -999)).slice(0, 5);
  const laggards = [...enriched].sort((a, b) => (a.changePct ?? 999) - (b.changePct ?? 999)).slice(0, 5);
  const strong5d = enriched.filter((item) => (item.change5d ?? 0) > 3).slice(0, 5);
  const weak5d = enriched.filter((item) => (item.change5d ?? 0) < -3).slice(0, 5);
  const fundDivergence = enriched
    .filter((item) => (item.mainNetInflow ?? 0) > 0 && Math.abs(item.changePct ?? 0) < 0.5)
    .sort((a, b) => (b.mainNetInflow ?? 0) - (a.mainNetInflow ?? 0))
    .slice(0, 5);

  return {
    type,
    sectors: ranked,
    leaders,
    laggards,
    rotation: {
      strong5d,
      weak5d,
      fundDivergence,
    },
    dataTime: (() => {
      const latest = rows.map((item) => item.quoteTime).filter(Boolean).sort().at(-1);
      return latest ? chinaDateTimeString(new Date(latest)) : null;
    })(),
    historyCoverage: {
      requested: ranked.length,
      attempted: candidates.length,
      succeeded: verifiedRankedCount,
    },
    enrichmentAttempts: {
      requested: candidates.length,
      succeeded: statsByCode.size,
    },
    warnings: enrichmentLimit === 0
      ? ['本次未执行候选板块20日K线复核，热度分数已排除20日分项并降低结论置信度']
      : (verifiedRankedCount < ranked.length
        ? [`最终板块榜单20日K线仅核验 ${verifiedRankedCount}/${ranked.length}，未核验项不计算20日贡献并降低结论置信度`]
        : []),
  };
}

async function fetchEastmoneySectors(type, limit) {
  const fs = type === 'concept' ? 'm:90+t:3+f:!50' : 'm:90+t:2+f:!50';
  const data = await fetchJson('https://push2.eastmoney.com/api/qt/clist/get', {
    params: {
      pn: 1,
      pz: limit,
      po: 1,
      np: 1,
      fltt: 2,
      invt: 2,
      fid: 'f3',
      fs,
      fields: SECTOR_FIELDS,
      ut: 'bd1d9ddb04089700cf9c27f6f7426281',
    },
  });
  const diff = data?.data?.diff;
  if (!Array.isArray(diff) || diff.length === 0) {
    throw new Error('无法获取东方财富板块数据');
  }
  return diff.map((item) => {
    const quoteTime = parseEpochSeconds(item.f124);
    return ({
    code: item.f12,
    name: item.f14,
    price: safeNumber(item.f2),
    changePct: safeNumber(item.f3),
    turnoverRate: safeNumber(item.f8),
    mainNetInflow: item.f62 == null ? null : round(safeNumber(item.f62) / 100000000, 2),
    superNetInflow: item.f66 == null ? null : round(safeNumber(item.f66) / 100000000, 2),
    riseCount: safeNumber(item.f104),
    fallCount: safeNumber(item.f105),
    flatCount: safeNumber(item.f106),
    change5d: safeNumber(item.f109),
    // 2. 不猜测供应商资金流字段为20日涨跌，等待候选K线复核后再填充。
    change20d: null,
    leadingStock: item.f128 ?? item.f136 ?? '',
    quoteTime: quoteTime?.toISOString() ?? null,
    tradeDate: quoteTime ? chinaDateString(quoteTime) : null,
  });
  });
}

async function fetchSectorKlineStats(code) {
  const data = await fetchJson('https://push2his.eastmoney.com/api/qt/stock/kline/get', {
    params: {
      secid: `90.${code}`,
      klt: 101,
      fqt: 1,
      beg: '20200101',
      end: '20500101',
      lmt: 30,
      fields1: 'f1,f2,f3,f4,f5,f6',
      fields2: 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
    },
  });
  const klines = data?.data?.klines;
  if (!Array.isArray(klines) || klines.length < 6) throw new Error('板块 K 线不足');
  const rows = klines.map((line) => {
    const [date, open, close, high, low, volume] = String(line).split(',');
    return {
      date,
      open: safeNumber(open),
      close: safeNumber(close),
      high: safeNumber(high),
      low: safeNumber(low),
      volume: safeNumber(volume),
    };
  }).filter((row) => Number.isFinite(row.close));
  const latest = rows.at(-1);
  const previous5 = rows.at(-6);
  const previous20 = rows.at(-21);
  const avgVolume5 = rows.slice(-6, -1).reduce((sum, row) => sum + (row.volume ?? 0), 0) / Math.min(5, rows.length - 1);
  return {
    change5d: previous5 ? round((latest.close - previous5.close) / previous5.close * 100, 2) : null,
    change20d: previous20 ? round((latest.close - previous20.close) / previous20.close * 100, 2) : null,
    volumeRatio: avgVolume5 ? round((latest.volume ?? 0) / avgVolume5, 2) : null,
  };
}

/**
 * 使用同类板块横截面分位数计算可复算热度，避免把百分比和亿元直接相加。
 */
export function calculateSectorHeatScore(sector, universe = [sector]) {
  return calculateSectorHeatBreakdown(sector, universe).score;
}

/**
 * 返回板块热度的原始值、标准化值、权重和贡献，使调用方能够完整回放结果。
 */
export function calculateSectorHeatBreakdown(sector, universe) {
  const safeUniverse = Array.isArray(universe) && universe.length ? universe : [sector];
  const available = Object.entries(HEAT_COMPONENTS).flatMap(([name, config]) => {
    const raw = finiteOrNull(sector[config.field]);
    if (raw == null) return [];
    const sample = safeUniverse
      .map((item) => finiteOrNull(item[config.field]))
      .filter((value) => value != null);
    return [[name, {
      raw,
      normalized: percentileScore(raw, sample),
      weight: config.weight,
      sampleSize: sample.length,
    }]];
  });
  const availableWeight = available.reduce((sum, [, item]) => sum + item.weight, 0);
  const components = Object.fromEntries(available.map(([name, item]) => {
    const effectiveWeight = availableWeight > 0 ? item.weight / availableWeight : 0;
    return [name, {
      ...item,
      effectiveWeight: round(effectiveWeight, 6),
      contribution: round(item.normalized * effectiveWeight, 4),
    }];
  }));
  return {
    score: round(Object.values(components)
      .reduce((sum, item) => sum + item.contribution, 0), 4),
    formulaVersion: HEAT_FORMULA_VERSION,
    normalization: HEAT_NORMALIZATION,
    availableWeight: round(availableWeight, 4),
    missingComponents: Object.keys(HEAT_COMPONENTS).filter((name) => components[name] == null),
    components,
  };
}

function rankSectorHeat(sectors) {
  return sectors.map((sector) => {
    const heatScoreBreakdown = calculateSectorHeatBreakdown(sector, sectors);
    return {
      ...sector,
      heatScore: heatScoreBreakdown.score,
      heatScoreBreakdown,
      heatScoreQuality: sector.historyVerified ? 'verified_20d' : 'limited_missing_20d',
    };
  });
}

function percentileScore(value, sample) {
  if (sample.length <= 1) return 50;
  const lower = sample.filter((item) => item < value).length;
  const equal = sample.filter((item) => item === value).length;
  return round((lower + Math.max(0, equal - 1) / 2) / (sample.length - 1) * 100, 4);
}

function finiteOrNull(value) {
  const number = Number(value);
  return value == null || !Number.isFinite(number) ? null : number;
}

function detectSectorRotation(sector) {
  const signals = [];
  if ((sector.changePct ?? 0) > 1.5 && (sector.change5d ?? 0) > 3) {
    signals.push('连续走强');
  }
  if ((sector.changePct ?? 0) < -1.5 && (sector.change5d ?? 0) < -3) {
    signals.push('连续走弱');
  }
  if ((sector.mainNetInflow ?? 0) > 0 && Math.abs(sector.changePct ?? 0) < 0.5) {
    signals.push('资金流入但价格滞涨');
  }
  if ((sector.mainNetInflow ?? 0) < 0 && (sector.changePct ?? 0) > 1) {
    signals.push('上涨但资金流出');
  }
  return signals.length ? signals.join(' / ') : '正常';
}
