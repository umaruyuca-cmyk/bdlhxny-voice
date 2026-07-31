import { fetchJson } from '../utils/api.js';
import { safeNumber, round } from '../analysis/technical.js';

const OVERSEAS_INDEXES = [
  { name: '纳斯达克', code: 'usIXIC', region: 'us' },
  { name: '道琼斯', code: 'usDJI', region: 'us' },
  { name: '标普500', code: 'usSPX', region: 'us' },
  { name: '英伟达', code: 'usNVDA', region: 'us' },
  { name: '恒生科技', code: 'hkHSTECH', region: 'hk' },
];

export async function fetchOvernightContext(options = {}) {
  try {
    const results = await Promise.all(
      OVERSEAS_INDEXES.map(async (index) => {
        try {
          return await fetchGlobalIndex(index, options);
        } catch (error) {
          return { name: index.name, code: index.code, region: index.region, error: error.message };
        }
      }),
    );

    const validIndices = results.filter((item) => !item.error);
    const context = classifyOvernight(validIndices);

    return { indices: results, context };
  } catch (error) {
    return null;
  }
}

async function fetchGlobalIndex(index, options = {}) {
  const data = await fetchJson('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get', {
    params: {
      param: `${index.code},day,,,3,qfq`,
    },
    headers: {
      Referer: 'https://gu.qq.com/',
    },
  });

  const stockData = data?.data?.[index.code];
  if (!stockData) throw new Error('返回空数据');

  const qtContainer = stockData.qt;
  const qt = qtContainer?.[index.code];
  if (!Array.isArray(qt) || qt.length < 35) throw new Error('qt数据不完整');

  const price = safeNumber(qt[3]);
  const preClose = safeNumber(qt[4]);
  const changePct = safeNumber(qt[32]);

  const dayRows = stockData.qfqday ?? stockData.day;
  const dayChanges = [];
  if (Array.isArray(dayRows)) {
    for (const row of dayRows) {
      const open = safeNumber(row[1]);
      const close = safeNumber(row[2]);
      if (open != null && close != null) {
        dayChanges.push(round((close - open) / open * 100, 2));
      }
    }
  }

  return {
    name: index.name,
    code: index.code,
    region: index.region,
    price,
    preClose,
    open: safeNumber(qt[5]),
    changeAmount: safeNumber(qt[31]),
    changePct,
    high: safeNumber(qt[33]),
    low: safeNumber(qt[34]),
    dayChanges,
  };
}

function classifyOvernight(indices) {
  if (indices.length === 0) return { bias: '未知', summary: '海外数据暂不可用' };

  const upCount = indices.filter((i) => i.changePct > 0).length;
  const downCount = indices.filter((i) => i.changePct < 0).length;
  const total = indices.length;

  const nvda = indices.find((i) => i.code === 'usNVDA');
  const nasdaq = indices.find((i) => i.code === 'usIXIC');
  const hstech = indices.find((i) => i.code === 'hkHSTECH');

  let bias = '中性';
  if (upCount >= total * 0.7 || upCount > downCount * 2) {
    bias = '顺风';
  } else if (downCount >= total * 0.7 || downCount > upCount * 2) {
    bias = '逆风';
  }

  const parts = [];
  if (upCount > 0) {
    const names = indices.filter((i) => i.changePct > 0).map((i) => `${i.name}${fmtChange(i.changePct)}`).join(' ');
    parts.push(names);
  }
  if (downCount > 0) {
    const names = indices.filter((i) => i.changePct < 0).map((i) => `${i.name}${fmtChange(i.changePct)}`).join(' ');
    parts.push(names);
  }

  if (nvda && nvda.changePct > 1) parts.push('AI/半导体偏强');
  if (nvda && nvda.changePct < -1) parts.push('AI/半导体偏弱');
  if (hstech && hstech.changePct < -1.5) parts.push('中国资产承压');

  const summary = parts.length > 0 ? parts.join(' | ') : '涨跌互现';

  return { bias, summary };
}

function fmtChange(pct) {
  if (pct == null) return '';
  const sign = pct > 0 ? '+' : '';
  return `${sign}${pct.toFixed(2)}%`;
}
