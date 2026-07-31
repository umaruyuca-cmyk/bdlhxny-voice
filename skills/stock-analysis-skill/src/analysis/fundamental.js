/**
 * 基本面筛查模块
 * 基于 PE / PB / 市值做基础筛查，产生红旗/警告/扣分/否决。
 * 仅 Eastmoney 数据源有完整字段；Sina 回退源无 PE/PB/市值时安全降级。
 */

export function screenFundamentals(quote) {
  const pe = quote.peRatio ?? null;
  const pb = quote.pbRatio ?? null;
  const marketCap = quote.totalMarketValue ?? null;

  const redFlags = [];
  const warnings = [];
  let adjustment = 0;
  let veto = false;

  // PE 评估（仅最高严重等级生效，不叠加）
  if (pe != null) {
    if (pe < 0) {
      redFlags.push('当前亏损(PE为负)');
      adjustment -= 15;
    } else if (pe > 300) {
      redFlags.push('PE畸高(>300)');
      adjustment -= 10;
      veto = true;
    } else if (pe > 200) {
      warnings.push('PE过高(>200)');
      adjustment -= 10;
    } else if (pe > 100) {
      warnings.push('PE偏高(>100)');
      adjustment -= 5;
    }
  }

  // PB 评估
  if (pb != null) {
    if (pb > 20) {
      redFlags.push('市净率过高(PB>20)');
    } else if (pb > 10) {
      warnings.push('PB偏高(>10)');
      adjustment -= 5;
    } else if (pb < 1) {
      adjustment += 3;
    }
  }

  // 市值评估（单位：元 → 亿）
  if (marketCap != null) {
    const marketCapYi = marketCap / 1e8;
    if (marketCapYi < 30) {
      redFlags.push('微盘股(市值<30亿)');
    } else if (marketCapYi < 50) {
      warnings.push('市值偏小(<50亿)');
      adjustment -= 3;
    }
  }

  // 扣分下限 -20
  adjustment = Math.max(-20, adjustment);

  // 否决条件：PE为负且红旗≥2，或PE>300（已在上面设置）
  if (pe != null && pe < 0 && redFlags.length >= 2) {
    veto = true;
  }

  return {
    redFlags,
    warnings,
    adjustment,
    veto,
    indicators: { pe, pb, marketCap },
  };
}
