"""Analysis Engine 测试：可复现性 + 各分析类型行为 + 数据缺失降级。"""

from __future__ import annotations

from stockwise_analysis.contracts.analysis import AnalysisInput
from stockwise_analysis.contracts.observation import DataQuality
from stockwise_analysis.domain.analysis_engine import analyze

# 确定性合成K线：60 根缓涨序列（与 mock 不同，这里手工构造便于断言）
_SYNTHETIC_BARS = [
    {"date": f"2026-01-{i+1:02d}", "open": 100.0 + i, "high": 102.0 + i, "low": 99.0 + i, "close": 101.0 + i, "volume": 1000000}
    for i in range(60)
]


def _make_input(
    analysis_type: str,
    *,
    bars: list[dict] | None = None,
    quality: str = "OK",
    quote: dict | None = None,
) -> AnalysisInput:
    """构造标准 AnalysisInput，默认带 60 根K线和 OK 质量。"""
    return AnalysisInput(
        analysis_id="t-engine",
        analysis_type=analysis_type,
        instrument={"symbol": "600519", "name": "茅台"},
        realtime_quote=quote,
        historical_prices=bars if bars is not None else _SYNTHETIC_BARS,
        data_quality=DataQuality(completeness=1.0, quality_status=quality),
        methodology_version="python-analysis.v2",
    )


# ── 可复现性 ──


def test_analyze_is_deterministic():
    """相同输入两次调用结果完全一致（回测可复现的核心保证）。"""
    first = analyze(_make_input("comprehensive"))
    second = analyze(_make_input("comprehensive"))
    assert first.model_dump() == second.model_dump()


# ── 各分析类型 ──


def test_technical_computes_indicators():
    """technical 类型应算出 MA/MACD/RSI/波动率。"""
    result = analyze(_make_input("technical"))
    assert result.status == "SUCCESS"
    ind = result.calculated_indicators
    assert "ma5" in ind and "ma20" in ind
    assert "rsi" in ind
    assert "macd" in ind
    assert "volatility_annualized" in ind
    # 缓涨序列 MA 多头排列 → 应有 bullish 信号
    assert any(s["direction"] == "bullish" for s in result.signals)


def test_market_snapshot_needs_only_quote():
    """market_snapshot 无历史K线也能出结果（快路径）。"""
    result = analyze(_make_input("market_snapshot", bars=[], quote={"price": 130.0}))
    assert result.status in {"SUCCESS", "PARTIAL"}
    assert "snapshot" in result.calculated_indicators


def test_market_snapshot_without_quote_is_explicitly_limited():
    """实时行情缺失时不得生成“分析完成”类结论。"""
    result = analyze(_make_input("market_snapshot", bars=[], quote=None, quality="OK"))

    assert result.status == "LIMITED"
    assert any("实时行情数据缺失" in item for item in result.limitations)
    assert result.conclusions == [{"text": "数据不足，无法形成可靠分析结论", "confidence": "LOW"}]


def test_comprehensive_includes_risk():
    """comprehensive 应包含年化收益/夏普/回撤。"""
    result = analyze(_make_input("comprehensive"))
    ind = result.calculated_indicators
    assert "annualized_return" in ind
    assert "sharpe" in ind
    assert "max_drawdown" in ind


# ── 数据缺失降级 ──


def test_technical_without_history_is_limited():
    """technical 无历史K线 → LIMITED，不编造指标。"""
    result = analyze(_make_input("technical", bars=[]))
    assert result.status == "LIMITED"
    assert any("历史K线不足" in lim for lim in result.limitations)
    assert "ma5" not in result.calculated_indicators


def test_partial_quality_propagates():
    """输入 PARTIAL 质量 → 输出 PARTIAL 且保留 limitation。"""
    result = analyze(_make_input("technical", quality="PARTIAL"))
    assert result.status == "PARTIAL"


def test_invalid_quality_is_limited():
    """输入 INVALID 质量 → LIMITED。"""
    result = analyze(_make_input("market_snapshot", quality="INVALID"))
    assert result.status == "LIMITED"


# ── 分析工具封装 ──


def test_analysis_tool_registered_and_callable():
    """analysis.run_analysis 工具注册后可调用并返回 AnalysisResult。"""
    from stockwise_analysis.tools.analysis_tool import register_analysis_tools
    from stockwise_analysis.tools.registry import ToolRegistry

    registry = ToolRegistry()
    register_analysis_tools(registry)
    tool = registry.get("analysis.run_analysis")
    assert tool.read_only is True

    result = tool.handler(_make_input("technical").model_dump())
    assert result["status"] == "SUCCESS"
    assert "ma5" in result["calculated_indicators"]
