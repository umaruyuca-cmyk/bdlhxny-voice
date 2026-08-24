"""Python Analysis Engine：分析能力的默认实现。

这是 Prompt v3.1 §10 "分析能力部署形态后置" 的第一阶段实现——纯 Python
模块，零框架依赖，只消费标准化的 AnalysisInput，不查询任何外部数据。

核心保证：
1. 纯函数：analyze(input) -> result，相同输入永远相同输出（可复现）；
2. 无 I/O：不访问 MCP/Java/数据库/行情接口；
3. 防未来函数：所有指标只使用截至当前的数据点；
4. 观察驱动：有哪些 Observation 就算哪些指标，只有 quote 时仍能出快照。

计算责任（架构文档 v3.1 §8.3）：
OHLCV → MA/EMA/MACD/RSI/ATR → 波动率/最大回撤/支撑阻力 → 信号/风险标记/结论。
"""

from __future__ import annotations

import logging
from typing import Any

from bdlh_runtime.contracts.analysis import AnalysisInput, AnalysisResult

from . import indicators as ind
from . import risk as risk_metrics

logger = logging.getLogger("bdlh_runtime.compute.analysis_engine")

# 分析引擎版本号，随计算逻辑变更递增（写入 methodology_version 供溯源）
ENGINE_VERSION = "python-analysis.v2"
FINANCE_RESEARCH_M2_METHODOLOGY = "finance-research.m2"

# 各指标的标准参数（集中定义，保证复现性和跨调用一致性）
INDICATOR_PARAMS = {
    "ma_windows": (5, 10, 20, 60),
    "macd": {"fast_span": 12, "slow_span": 26, "signal_span": 9},
    "rsi_window": 14,
    "atr_window": 14,
    "lookback": 20,
}


def analyze(analysis_input: AnalysisInput) -> AnalysisResult:
    """执行分析并返回结构化结果（纯函数，无副作用）。

    观察驱动（重写 §6.2）：有哪些 Observation 就算哪些——只有 quote 时
    仍能出快照；关键数据（历史K线）缺失只标记 limitation，不编造指标。
    """

    prices = _extract_closes(analysis_input.historical_prices)

    calculated: dict[str, Any] = {"engine": ENGINE_VERSION}
    signals: list[dict[str, Any]] = []
    risk_flags: list[dict[str, Any]] = []
    limitations: list[str] = []
    if analysis_input.data_quality.known_unavailable:
        limitations.append("数据能力不可用: " + ", ".join(analysis_input.data_quality.known_unavailable))

    # ── 数据状态判断 ──
    has_history = len(prices) >= 20  # 至少够算 20 日窗口的指标
    has_quote = analysis_input.realtime_quote is not None

    # ── 观察驱动计算：有什么算什么 ──
    if has_quote:
        quote = analysis_input.realtime_quote
        calculated["snapshot"] = {
            "symbol": analysis_input.instrument.symbol,
            "price": quote.get("price", quote.get("close")),
            "as_of": quote.get("as_of", quote.get("date")),
        }

    if has_history:
        highs, lows, closes = _extract_ohlc(analysis_input.historical_prices)
        technical = _technical_analysis(prices, analysis_input, limitations, highs=highs, lows=lows, closes=closes)
        calculated.update(technical["indicators"])
        signals.extend(technical["signals"])
        risk_flags.extend(technical["risk_flags"])
        risk = _risk_summary(analysis_input, limitations, prices)
        calculated.update(risk["indicators"])
        risk_flags.extend(risk["risk_flags"])

    if analysis_input.financial_data is not None:
        fundamental = _fundamental_analysis(analysis_input, limitations)
        calculated.update(fundamental["indicators"])
        risk_flags.extend(fundamental["risk_flags"])

    if analysis_input.portfolio_context is not None:
        portfolio = _portfolio_analysis(analysis_input, limitations)
        calculated.update(portfolio["indicators"])
        signals.extend(portfolio["signals"])
        risk_flags.extend(portfolio["risk_flags"])

    # ── 状态判定（观察驱动）：无任何业务数据 → LIMITED ──
    has_any_business_data = (
        has_quote
        or has_history
        or analysis_input.financial_data is not None
        or analysis_input.valuation_data is not None
        or analysis_input.portfolio_context is not None
    )
    status = _decide_status(analysis_input, has_any_business_data, limitations)

    # ── 结论：由确定性信号生成，不依赖 LLM ──
    conclusions = (
        [{"text": "数据不足，无法形成可靠分析结论", "confidence": "LOW"}]
        if status == "LIMITED"
        else _build_conclusions(signals, risk_flags)
    )

    return AnalysisResult(
        analysis_id=analysis_input.analysis_id,
        status=status,
        facts=[{"name": "instrument", "value": analysis_input.instrument.model_dump()}],
        calculated_indicators=calculated,
        signals=signals,
        risk_flags=risk_flags,
        conclusions=conclusions,
        limitations=limitations,
        data_quality=analysis_input.data_quality,
        provenance=analysis_input.provenance,
        methodology_version=ENGINE_VERSION,
    )


# ── 内部计算函数 ──


def _extract_closes(bars: list[dict[str, Any]]) -> list[float]:
    """从历史K线提取收盘价序列（时间正序）。

    兼容两种字段命名：close / 收盘。过滤 None 和缺失。
    """

    closes: list[float] = []
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        close = bar.get("close", bar.get("收盘"))
        if close is not None:
            try:
                closes.append(float(close))
            except (TypeError, ValueError):
                continue
    return closes


def _extract_ohlc(bars: list[dict[str, Any]]) -> tuple[list[float], list[float], list[float]]:
    """从历史K线提取 OHLC 三序列（high/low/close），用于 ATR 和支撑阻力。"""

    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        try:
            high = float(bar.get("high", bar.get("最高")))
            low = float(bar.get("low", bar.get("最低")))
            close = float(bar.get("close", bar.get("收盘")))
        except (TypeError, ValueError):
            continue
        highs.append(high)
        lows.append(low)
        closes.append(close)
    return highs, lows, closes


def _technical_analysis(
    prices: list[float],
    analysis_input: AnalysisInput,
    limitations: list[str],
    *,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    closes: list[float] | None = None,
) -> dict[str, Any]:
    """技术指标 + 信号 + 风险标记（审查文档 §6.2：补齐 ATR/支撑阻力接线）。"""

    indicators: dict[str, Any] = {}

    # MA 多周期
    ma_windows = INDICATOR_PARAMS["ma_windows"]
    for window in ma_windows:
        ma = ind.simple_moving_average(prices, window)
        if ma is not None:
            indicators[f"ma{window}"] = round(ma, 4)

    # MACD
    macd = ind.macd_series(prices, **INDICATOR_PARAMS["macd"])
    indicators["macd"] = {
        "dif": _round_last(macd["dif"]),
        "dea": _round_last(macd["dea"]),
        "histogram": _round_last(macd["histogram"]),
    }

    # RSI
    rsi = ind.rsi_series(prices, INDICATOR_PARAMS["rsi_window"])
    indicators["rsi"] = _round_last(rsi)

    # ATR（需要 OHLC；审查文档 §6.2）
    if highs and lows and closes and len(highs) == len(lows) == len(closes):
        atr = ind.atr_series(highs, lows, closes, INDICATOR_PARAMS["atr_window"])
        indicators["atr"] = _round_last(atr)

    # 支撑/阻力位（需要 OHLC）
    if highs and lows:
        sr = risk_metrics.support_resistance(highs, lows, INDICATOR_PARAMS["lookback"])
        indicators["support"] = _round(sr.get("support"))
        indicators["resistance"] = _round(sr.get("resistance"))

    # 风险类（technical 也带基础波动率和回撤）
    returns = _simple_returns(prices)
    indicators["volatility_annualized"] = _round(risk_metrics.annualized_volatility(returns))
    indicators["max_drawdown"] = _round(risk_metrics.maximum_drawdown(prices))

    # 信号判定（确定性规则）
    signals: list[dict[str, Any]] = []
    risk_flags: list[dict[str, Any]] = []

    # MA 多头排列：ma5 > ma10 > ma20
    ma5, ma10, ma20 = (indicators.get(f"ma{w}") for w in (5, 10, 20))
    if None not in (ma5, ma10, ma20) and ma5 > ma10 > ma20:
        signals.append({"name": "ma_bullish_alignment", "direction": "bullish", "strength": "medium"})
    elif None not in (ma5, ma10, ma20) and ma5 < ma10 < ma20:
        signals.append({"name": "ma_bearish_alignment", "direction": "bearish", "strength": "medium"})

    # RSI 超买超卖
    rsi_val = indicators.get("rsi")
    if rsi_val is not None:
        if rsi_val >= 70:
            risk_flags.append({"name": "rsi_overbought", "severity": "high", "detail": f"RSI={rsi_val:.1f} 超买"})
        elif rsi_val <= 30:
            signals.append({"name": "rsi_oversold", "direction": "reversal_up", "strength": "low"})

    # MACD 金叉死叉
    dif, dea = macd["dif"], macd["dea"]
    if dif is not None and dea is not None and len(dif) > 1 and len(dea) > 1:
        # 用最后两日判断交叉（防未来函数：只用已发生数据）
        dif_prev, dif_cur = dif[-2], dif[-1]
        dea_prev, dea_cur = dea[-2], dea[-1]
        if None not in (dif_prev, dif_cur, dea_prev, dea_cur):
            if dif_prev <= dea_prev and dif_cur > dea_cur:
                signals.append({"name": "macd_golden_cross", "direction": "bullish", "strength": "low"})
            elif dif_prev >= dea_prev and dif_cur < dea_cur:
                signals.append({"name": "macd_death_cross", "direction": "bearish", "strength": "low"})

    return {"indicators": indicators, "signals": signals, "risk_flags": risk_flags}


def _fundamental_analysis(analysis_input: AnalysisInput, limitations: list[str]) -> dict[str, Any]:
    """基本面筛查：基于财务数据产出去重后的风险标记。

    目前是确定性规则：无财务数据时标记为"无基本面数据"，不编造。
    """

    indicators: dict[str, Any] = {}
    risk_flags: list[dict[str, Any]] = []

    financial = analysis_input.financial_data
    if not financial:
        limitations.append("财务数据缺失，无法进行基本面筛查")
        return {"indicators": indicators, "risk_flags": risk_flags}

    # 后续扩展：PE/PB 阈值、营收增速、负债率等确定性规则
    indicators["financial_found"] = True
    return {"indicators": indicators, "risk_flags": risk_flags}


def _risk_summary(analysis_input: AnalysisInput, limitations: list[str], prices: list[float]) -> dict[str, Any]:
    """comprehensive 的综合风险汇总。"""

    indicators: dict[str, Any] = {}
    risk_flags: list[dict[str, Any]] = []

    if prices:
        returns = _simple_returns(prices)
        indicators["annualized_return"] = _round(risk_metrics.annualized_return(prices))
        indicators["sharpe"] = _round(risk_metrics.sharpe_ratio(returns))
        mdd = risk_metrics.maximum_drawdown(prices)
        indicators["max_drawdown"] = _round(mdd)
        if mdd is not None and mdd < -0.2:
            risk_flags.append({"name": "deep_drawdown", "severity": "high", "detail": f"最大回撤 {mdd:.1%}"})

    return {"indicators": indicators, "risk_flags": risk_flags}


def _portfolio_analysis(analysis_input: AnalysisInput, limitations: list[str]) -> dict[str, Any]:
    """组合影响分析：分析标的与用户持仓的重合和盈亏。

    确定性规则（无 LLM）：
    1. 找出持仓中与分析标的重合的仓位（same symbol）；
    2. 计算该仓位的浮动盈亏（成本价 vs 当前价）；
    3. 若分析标的不在持仓中，输出"未持有"提示，供 Summary Model 表达。

    portfolio_context 缺失时标记 limitation 并返回空结果（不编造）。
    """

    indicators: dict[str, Any] = {}
    signals: list[dict[str, Any]] = []
    risk_flags: list[dict[str, Any]] = []

    portfolio = analysis_input.portfolio_context
    if not portfolio:
        limitations.append("持仓数据缺失，无法进行组合影响分析")
        return {"indicators": indicators, "signals": signals, "risk_flags": risk_flags}

    target_symbol = analysis_input.instrument.symbol
    positions = portfolio.get("positions", []) if isinstance(portfolio, dict) else []

    # 找与分析标的重合的持仓
    holdings = [p for p in positions if str(p.get("symbol", "")).strip() == target_symbol]

    if holdings:
        for h in holdings:
            cost = h.get("cost_price")
            qty = h.get("quantity", 0)
            # 当前价优先用 realtime_quote，其次持仓自带 current_price
            current = None
            if analysis_input.realtime_quote is not None:
                current = analysis_input.realtime_quote.get("price", analysis_input.realtime_quote.get("close"))
            current = current if current is not None else h.get("current_price")

            pnl = None
            if cost and current:
                pnl = (current / cost - 1.0) * qty * cost  # 浮动盈亏金额
            indicators[f"holding_{target_symbol}"] = {
                "quantity": qty,
                "cost_price": cost,
                "current_price": current,
                "pnl_amount": _round(pnl, 2) if pnl is not None else None,
            }
            if pnl is not None and pnl < 0:
                risk_flags.append(
                    {"name": "position_unrealized_loss", "severity": "medium", "detail": f"{target_symbol} 浮动亏损"}
                )
            elif pnl is not None and pnl > 0:
                signals.append({"name": "position_unrealized_gain", "direction": "bullish", "strength": "low"})
    else:
        indicators["holding_match"] = {"found": False, "symbol": target_symbol}

    # 组合集中度：该标的占组合比例（若持仓里有市值信息）
    total_market_value = sum(
        (p.get("quantity", 0) or 0) * (p.get("current_price") or 0) for p in positions if p.get("current_price")
    )
    if total_market_value > 0 and holdings:
        holding_mv = holdings[0].get("quantity", 0) * (holdings[0].get("current_price") or 0)
        indicators["portfolio_concentration"] = round(holding_mv / total_market_value, 4)

    return {"indicators": indicators, "signals": signals, "risk_flags": risk_flags}


def _decide_status(
    analysis_input: AnalysisInput,
    has_any_business_data: bool,
    limitations: list[str],
) -> str:
    """观察驱动状态判定：无任何业务数据 → LIMITED；有缺口 → PARTIAL。"""

    base_quality = analysis_input.data_quality.quality_status
    if base_quality in ("INVALID", "FAILED"):
        return "LIMITED"
    if not has_any_business_data:
        return "LIMITED"
    if base_quality in ("PARTIAL", "STALE") or limitations:
        return "PARTIAL"
    return "SUCCESS"


def _build_conclusions(signals: list[dict], risk_flags: list[dict]) -> list[dict]:
    """由确定性信号生成结论，不依赖 LLM（供 Summary Model 二次加工）。"""

    if not signals and not risk_flags:
        return [{"text": "分析完成，无显著信号", "confidence": "LOW"}]

    conclusions: list[dict] = []
    bullish = [s for s in signals if s.get("direction") == "bullish"]
    bearish = [s for s in signals if s.get("direction") == "bearish"]

    if bullish and not bearish:
        conclusions.append(
            {"text": "技术面偏多（" + ",".join(s["name"] for s in bullish) + "）", "confidence": "MEDIUM"}
        )
    elif bearish and not bullish:
        conclusions.append(
            {"text": "技术面偏空（" + ",".join(s["name"] for s in bearish) + "）", "confidence": "MEDIUM"}
        )
    elif bullish and bearish:
        conclusions.append({"text": "技术信号多空交织，需谨慎", "confidence": "LOW"})

    if risk_flags:
        high_risks = [r for r in risk_flags if r.get("severity") == "high"]
        if high_risks:
            conclusions.append(
                {"text": "存在高风险标记：" + ",".join(r["name"] for r in high_risks), "confidence": "MEDIUM"}
            )

    return conclusions


# ── 工具函数 ──


def _simple_returns(prices: list[float]) -> list[float]:
    """价格序列 → 简单收益率序列（本地实现，避免跨模块依赖）。"""

    returns: list[float] = []
    for prev, cur in zip(prices, prices[1:], strict=False):
        if prev != 0:
            returns.append(cur / prev - 1.0)
    return returns


def _round(value: float | None, digits: int = 4) -> float | None:
    """统一舍入，保证输出可复现且简洁。"""

    return round(value, digits) if value is not None else None


def _round_last(values: list[float | None], digits: int = 4) -> float | None:
    """取序列最后一个非 None 值并舍入（用于指标"当前值"）。"""

    for value in reversed(values):
        if value is not None:
            return round(value, digits)
    return None
