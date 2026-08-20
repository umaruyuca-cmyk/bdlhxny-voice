"""动量轮动量化模块（从 skill quant.js 迁移，已验证算法）。

本模块迁移自 skills/stock-analysis-skill/src/analysis/quant.js，保留经
quant.test.js 验证过的核心算法（动量/排名/逆波动率配置/市场regime）。

设计原则（与 domain 其他模块一致）：
- 零框架依赖：不 import langgraph/langchain/mcp/mem0；
- 纯函数计算：输入历史价格序列，输出确定性结果，可复现；
- 算法对照 skill quant.js + quant.test.js 测试用例验证值。

不迁移的部分：
- calculateAnnualizedVolatility：已在 risk.py 实现（annualized_volatility），复用；
- backtestMomentumRotation：domain/backtest.py 已有更通用的 run_backtest。
"""

from __future__ import annotations

from typing import Any

# ── 默认配置（与 skill quant.js DEFAULT_QUANT_CONFIG 对齐）──
DEFAULT_QUANT_CONFIG: dict[str, Any] = {
    "lookbacks": [20, 60, 120],
    "momentum_weights": [0.4, 0.35, 0.25],
    "trend_ma_period": 60,
    "volatility_period": 20,
    "regime_ma_period": 200,
    "regime_volatility_lookback": 252,
    "regime_max_volatility_percentile": 0.8,
    "target_annual_volatility": 0.12,
    "max_asset_weight": 0.35,
    "select_count": 3,
    "rebalance_every": 5,
    "annual_trading_days": 252,
    "transaction_cost_rate": 0.0003,
}


def _finite_rows(history: list[dict]) -> list[dict]:
    """过滤有效行（有 date、close 为正有限值），按日期升序。

    对照 skill quant.js finiteRows（L49-54）。
    """
    rows = [row for row in history if row.get("date") and _is_finite_positive(row.get("close"))]
    return sorted(rows, key=lambda r: str(r["date"]))


def _is_finite_positive(value: Any) -> bool:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    return v > 0


def _sample_std(values: list[float]) -> float | None:
    """样本标准差（n-1 分母）。对照 quant.js sampleStd（L60-65）。"""
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    variance = sum((v - avg) ** 2 for v in values) / (len(values) - 1)
    return variance**0.5


def calculate_momentum(history: list[dict], lookback: int) -> float | None:
    """计算指定回看窗口的动量收益率。

    公式：latest_close / base_close - 1，base 为 lookback+1 期前的收盘价。
    对照 quant.js calculateMomentum（L67-73）。

    Args:
        history: K线序列，每行需有 date/close
        lookback: 回看窗口（正整数）

    Returns:
        动量收益率，数据不足返回 None
    """
    rows = _finite_rows(history)
    if not isinstance(lookback, int) or lookback < 1 or len(rows) <= lookback:
        return None
    latest = rows[-1]["close"]
    base = rows[-(lookback + 1)]["close"]
    return latest / base - 1 if base > 0 else None


def _annualized_volatility_from_rows(
    rows: list[dict], period: int = 20, annual_trading_days: int = 252
) -> float | None:
    """年化波动率（对数收益率样本标准差 × sqrt(年交易日)）。

    对照 quant.js calculateAnnualizedVolatility（L75-82）。
    domain/risk.py 的 annualized_volatility 接收 returns 序列，这里接收原始 rows，
    内部取最近 period+1 根 close 计算对数收益率。
    """
    if len(rows) <= period:
        return None
    closes = [r["close"] for r in rows[-(period + 1) :]]
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    daily_vol = _sample_std(returns)
    return daily_vol * (annual_trading_days**0.5) if daily_vol is not None else None


def _moving_average(values: list[float], period: int) -> list[float | None]:
    """简单移动平均序列。对照 skill technical.js movingAverage。"""
    result: list[float | None] = []
    for i in range(len(values)):
        if i + 1 < period:
            result.append(None)
        else:
            window = values[i + 1 - period : i + 1]
            result.append(sum(window) / period)
    return result


def _z_scores(values: list[float | None]) -> list[float | None]:
    """Z-score 标准化。对照 quant.js zScores（L114-123）。"""
    valid = [v for v in values if v is not None and _is_finite(v)]
    if not valid:
        return [None] * len(values)
    avg = sum(valid) / len(valid)
    dev = _sample_std(valid)
    if dev is None or dev == 0:
        return [0.0 if (v is not None and _is_finite(v)) else None for v in values]
    return [(v - avg) / dev if (v is not None and _is_finite(v)) else None for v in values]


def _is_finite(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def calculate_quant_features(history: list[dict], config: dict | None = None) -> dict:
    """计算单标的量化特征（动量/趋势MA/年化波动率）。

    对照 quant.js calculateQuantFeatures（L84-112）。

    Returns:
        {as_of, close, momentum: {lookback: value}, trend_ma, trend_eligible, annualized_volatility, complete}
    """
    settings = {**DEFAULT_QUANT_CONFIG, **(config or {})}
    rows = _finite_rows(history)
    closes = [r["close"] for r in rows]
    latest = rows[-1] if rows else None
    trend_ma_list = _moving_average(closes, settings["trend_ma_period"])
    trend_ma = trend_ma_list[-1] if trend_ma_list else None

    momentum = {lb: calculate_momentum(rows, lb) for lb in settings["lookbacks"]}
    volatility = _annualized_volatility_from_rows(rows, settings["volatility_period"], settings["annual_trading_days"])

    complete = (
        latest is not None
        and trend_ma is not None
        and volatility is not None
        and all(momentum[lb] is not None for lb in settings["lookbacks"])
    )

    return {
        "as_of": latest.get("date") if latest else None,
        "close": latest.get("close") if latest else None,
        "momentum": momentum,
        "trend_ma": trend_ma,
        "trend_eligible": bool(complete and latest and latest["close"] > trend_ma),
        "annualized_volatility": volatility,
        "complete": complete,
    }


def rank_momentum_universe(assets: list[dict], config: dict | None = None) -> list[dict]:
    """对多标的按动量Z-score加权排名。

    对照 quant.js rankMomentumUniverse（L125-148）。

    Args:
        assets: [{code, name?, history: [...]}]
        config: 可选配置覆盖

    Returns:
        按 score 降序排列的 [{code, name, features, score}]
    """
    settings = {**DEFAULT_QUANT_CONFIG, **(config or {})}
    evaluated = [
        {
            "code": a["code"],
            "name": a.get("name", a["code"]),
            "features": calculate_quant_features(a["history"], settings),
        }
        for a in assets
    ]

    z_by_lookback = {lb: _z_scores([e["features"]["momentum"][lb] for e in evaluated]) for lb in settings["lookbacks"]}

    ranked = []
    for i, asset in enumerate(evaluated):
        score_parts = []
        for w_idx, lb in enumerate(settings["lookbacks"]):
            z = z_by_lookback[lb][i]
            score_parts.append(z * settings["momentum_weights"][w_idx] if z is not None else None)
        score = sum(score_parts) if all(p is not None for p in score_parts) else None
        ranked.append({**asset, "score": score})

    ranked.sort(key=lambda x: x["score"] if x["score"] is not None else float("-inf"), reverse=True)
    return ranked


def allocate_inverse_volatility(ranked_assets: list[dict], config: dict | None = None) -> dict:
    """逆波动率配置（带单品种上限和目标波动率缩放）。

    对照 quant.js allocateInverseVolatility（L150-189）。
    迭代封顶再分配保证每只不超过 max_asset_weight。

    Returns:
        {weights: {code: weight}, cash_weight, estimated_volatility}
    """
    settings = {**DEFAULT_QUANT_CONFIG, **(config or {})}
    selected = [
        a
        for a in ranked_assets
        if a["features"]["complete"]
        and a["features"]["trend_eligible"]
        and a["score"] is not None
        and _is_finite(a["score"])
    ][: settings["select_count"]]

    if not selected:
        return {"weights": {}, "cash_weight": 1.0, "estimated_volatility": 0.0}

    inv_vol = [1.0 / a["features"]["annualized_volatility"] for a in selected]
    inv_sum = sum(inv_vol)
    base_weights = [v / inv_sum for v in inv_vol]

    # 迭代封顶再分配（对照 quant.js L162-170）
    for _ in range(len(selected)):
        capped = [min(w, settings["max_asset_weight"]) for w in base_weights]
        remaining = 1.0 - sum(capped)
        uncapped = [base_weights[i] if capped[i] < settings["max_asset_weight"] else 0.0 for i in range(len(selected))]
        uncapped_sum = sum(uncapped)
        base_weights = [
            w + remaining * uncapped[i] / uncapped_sum if uncapped_sum > 0 else w for i, w in enumerate(capped)
        ]

    estimated_vol = (
        sum((base_weights[i] * selected[i]["features"]["annualized_volatility"]) ** 2 for i in range(len(selected)))
    ) ** 0.5
    exposure_scale = min(1.0, settings["target_annual_volatility"] / estimated_vol) if estimated_vol > 0 else 0.0
    weights = {selected[i]["code"]: base_weights[i] * exposure_scale for i in range(len(selected))}
    invested = sum(weights.values())
    return {
        "weights": weights,
        "cash_weight": max(0.0, 1.0 - invested),
        "estimated_volatility": estimated_vol * exposure_scale,
    }


def evaluate_market_regime(history: list[dict], config: dict | None = None) -> dict:
    """评估市场状态（MA200 + 波动率分位）。

    对照 quant.js evaluateMarketRegime（L191-232）。
    eligible=True 表示 risk_on（价格在MA上方且波动率不极端）。

    Returns:
        {as_of, close, ma, annualized_volatility, volatility_percentile, eligible, complete}
    """
    settings = {**DEFAULT_QUANT_CONFIG, **(config or {})}
    rows = _finite_rows(history)
    closes = [r["close"] for r in rows]
    regime_ma_list = _moving_average(closes, settings["regime_ma_period"])
    regime_ma = regime_ma_list[-1] if regime_ma_list else None

    current_vol = _annualized_volatility_from_rows(rows, settings["volatility_period"], settings["annual_trading_days"])

    # 滚动计算历史波动率分位（对照 quant.js L201-216）
    vol_samples = []
    sample_start = max(
        settings["volatility_period"] + 1,
        len(rows) - settings["regime_volatility_lookback"],
    )
    for end in range(sample_start, len(rows) + 1):
        v = _annualized_volatility_from_rows(rows[:end], settings["volatility_period"], settings["annual_trading_days"])
        if v is not None:
            vol_samples.append(v)

    vol_percentile = None
    if current_vol is not None and vol_samples:
        vol_percentile = sum(1 for v in vol_samples if v <= current_vol) / len(vol_samples)

    complete = (
        len(rows) >= settings["regime_ma_period"]
        and regime_ma is not None
        and current_vol is not None
        and vol_percentile is not None
    )
    eligible = bool(
        complete and rows[-1]["close"] > regime_ma and vol_percentile <= settings["regime_max_volatility_percentile"]
    )

    return {
        "as_of": rows[-1].get("date") if rows else None,
        "close": rows[-1].get("close") if rows else None,
        "ma": regime_ma,
        "annualized_volatility": current_vol,
        "volatility_percentile": vol_percentile,
        "eligible": eligible,
        "complete": complete,
    }


# math 在文件底部 import，避免顶部污染（与 domain 其他模块风格一致）
import math  # noqa: E402
