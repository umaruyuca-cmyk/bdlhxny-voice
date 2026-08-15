"""动量轮动量化模块测试（对照 skill quant.test.js 验证值）。

本测试迁移自 skills/stock-analysis-skill/test/quant.test.js，确保 Python
domain/momentum.py 的算法与 skill Node 版本输出一致（可复现）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bdlh_runtime.domain.momentum import (
    allocate_inverse_volatility,
    calculate_momentum,
    evaluate_market_regime,
    rank_momentum_universe,
)


# ── 辅助：生成确定性历史K线（对照 quant.test.js makeHistory）──


def _make_history(days: int = 260, daily_return: float = 0.001, start: float = 100.0, volatility: float = 0.0) -> list[dict]:
    """生成确定性合成日K线。

    对照 quant.test.js makeHistory（L16-32）：偶数日 +volatility，奇数日 -volatility。
    """
    rows: list[dict] = []
    close = start
    origin = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(days):
        close *= 1 + daily_return + (volatility if i % 2 == 0 else -volatility)
        rows.append({
            "date": (origin + timedelta(days=i)).strftime("%Y-%m-%d"),
            "open": close,
            "close": close,
            "high": close,
            "low": close,
            "amount": 1e8,
        })
    return rows


# ── 测试1：动量只使用指定回看窗口（对照 quant.test.js L34-38）──


def test_momentum_uses_specified_lookback_window():
    history = _make_history(days=121, daily_return=0.001)
    expected = history[-1]["close"] / history[-21]["close"] - 1
    result = calculate_momentum(history, 20)
    assert result is not None
    assert abs(result - expected) < 1e-12


def test_momentum_returns_none_when_insufficient_data():
    history = _make_history(days=15, daily_return=0.001)
    assert calculate_momentum(history, 20) is None


# ── 测试2：波动率和排名为确定性计算（对照 quant.test.js L40-49）──


def test_volatility_and_ranking_are_deterministic():
    from bdlh_runtime.domain.momentum import _annualized_volatility_from_rows, _finite_rows

    steady = _make_history(daily_return=0.001, volatility=0.0002)
    fast = _make_history(daily_return=0.002, volatility=0.0004)

    vol_steady = _annualized_volatility_from_rows(_finite_rows(steady))
    vol_fast = _annualized_volatility_from_rows(_finite_rows(fast))
    assert vol_fast is not None and vol_steady is not None
    assert vol_fast > vol_steady

    ranking = rank_momentum_universe([
        {"code": "A", "history": steady},
        {"code": "B", "history": fast},
    ])
    assert ranking[0]["code"] == "B"  # 快的动量更高，排第一


# ── 测试3：逆波动率配置遵守单品种上限并保留现金（对照 quant.test.js L51-65）──


def test_inverse_volatility_respects_cap_and_keeps_cash():
    ranking = rank_momentum_universe([
        {"code": "A", "history": _make_history(daily_return=0.001, volatility=0.001)},
        {"code": "B", "history": _make_history(daily_return=0.0012, volatility=0.002)},
        {"code": "C", "history": _make_history(daily_return=0.0014, volatility=0.003)},
    ])
    allocation = allocate_inverse_volatility(ranking, {
        "select_count": 3,
        "max_asset_weight": 0.35,
        "target_annual_volatility": 0.05,
    })
    # 所有权重不超过 max_asset_weight（带浮点容差）
    for w in allocation["weights"].values():
        assert w <= 0.35 + 1e-7
    # 现金权重非负
    assert allocation["cash_weight"] >= 0
    # 权重总和不超过 1
    assert sum(allocation["weights"].values()) <= 1.0


def test_inverse_volatility_empty_when_no_eligible():
    """全部不满足趋势条件时返回全现金。"""
    falling = _make_history(days=260, daily_return=-0.001)
    ranking = rank_momentum_universe([{"code": "A", "history": falling}])
    allocation = allocate_inverse_volatility(ranking)
    assert allocation["weights"] == {}
    assert allocation["cash_weight"] == 1.0


# ── 测试4：市场状态在基准跌破MA200时转为risk_off（对照 quant.test.js L85-100）──


def test_market_regime_turns_off_when_benchmark_below_ma():
    falling_benchmark = _make_history(days=320, daily_return=-0.001, volatility=0.0002)
    regime = evaluate_market_regime(falling_benchmark)
    assert regime["eligible"] is False  # 下跌基准 → risk_off


def test_market_regime_complete_with_enough_data():
    rising = _make_history(days=320, daily_return=0.001)
    regime = evaluate_market_regime(rising)
    assert regime["complete"] is True
    assert regime["ma"] is not None
    assert regime["annualized_volatility"] is not None


# ── 测试5：数据不足时返回 None/不完整（边界）──


def test_market_regime_incomplete_with_short_history():
    short = _make_history(days=50, daily_return=0.001)
    regime = evaluate_market_regime(short)
    assert regime["complete"] is False


def test_quant_features_incomplete_with_short_history():
    from bdlh_runtime.domain.momentum import calculate_quant_features

    short = _make_history(days=30, daily_return=0.001)
    features = calculate_quant_features(short)
    assert features["complete"] is False
