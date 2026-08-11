"""组合影响分析测试（Phase 4）。"""

from __future__ import annotations

import pytest

from stockwise_analysis.contracts.analysis import AnalysisInput
from stockwise_analysis.contracts.observation import DataQuality
from stockwise_analysis.domain.analysis_engine import analyze
from stockwise_analysis.tools.java_data_adapter import (
    HttpJavaDataAdapter,
    create_java_adapter,
)


def _portfolio_input(portfolio: dict | None, *, symbol: str = "600519", quote: dict | None = None) -> AnalysisInput:
    """构造带持仓上下文的 portfolio_impact 输入。"""
    return AnalysisInput(
        analysis_id="t-portfolio",
        analysis_type="portfolio_impact",
        instrument={"symbol": symbol, "name": "茅台"},
        realtime_quote=quote,
        historical_prices=[],
        portfolio_context=portfolio,
        data_quality=DataQuality(completeness=1.0, quality_status="OK"),
    )


# ── 组合分析 ──


def test_portfolio_impact_finds_holding():
    """分析标的正被持有 → 输出持仓明细和盈亏。"""
    portfolio = {
        "positions": [
            {"symbol": "600519", "quantity": 100, "cost_price": 1500.0, "current_price": None},
        ]
    }
    result = analyze(_portfolio_input(portfolio, quote={"price": 1650.0}))
    assert result.status in {"SUCCESS", "PARTIAL"}
    holding = result.calculated_indicators.get("holding_600519")
    assert holding is not None
    assert holding["quantity"] == 100
    # 1650 vs 1500 成本 → 盈利 (1650/1500-1)*100*1500 = 15000
    assert holding["pnl_amount"] == pytest.approx(15000.0)


def test_portfolio_impact_not_held():
    """分析标的不在持仓 → 输出未持有标记，不编造盈亏。"""
    portfolio = {"positions": [{"symbol": "000001", "quantity": 100, "cost_price": 10.0, "current_price": None}]}
    result = analyze(_portfolio_input(portfolio, symbol="600519"))
    assert result.calculated_indicators.get("holding_match") == {"found": False, "symbol": "600519"}
    assert "holding_600519" not in result.calculated_indicators


def test_portfolio_impact_loss_flagged():
    """持仓浮亏 → 产生风险标记。"""
    portfolio = {
        "positions": [
            {"symbol": "600519", "quantity": 100, "cost_price": 2000.0, "current_price": None},
        ]
    }
    result = analyze(_portfolio_input(portfolio, quote={"price": 1500.0}))
    assert any(r["name"] == "position_unrealized_loss" for r in result.risk_flags)


def test_portfolio_impact_without_context_is_partial():
    """无持仓数据 → PARTIAL + limitation，不编造。"""
    result = analyze(_portfolio_input(None))
    assert result.status == "PARTIAL"
    assert any("持仓数据缺失" in lim for lim in result.limitations)


def test_portfolio_impact_no_history_needed():
    """组合分析不依赖历史K线（空 history 也能算）。"""
    result = analyze(_portfolio_input({"positions": []}))
    assert result.status != "LIMITED"


# ── Java Data Adapter ──


@pytest.mark.asyncio
async def test_java_adapter_mock_when_no_base_url():
    """无 base_url 时 Adapter 返回带 is_mock 标记的 mock 持仓。"""
    adapter = create_java_adapter(base_url=None)
    obs = await adapter.execute("portfolio.get_current_positions", {"user_id": "u1"})
    assert obs.status == "SUCCESS"
    assert obs.data["is_mock"] is True
    assert obs.data["user_id"] == "u1"
    assert len(obs.data["positions"]) > 0


@pytest.mark.asyncio
async def test_java_adapter_rejects_unknown_capability():
    """白名单外的能力被拒绝。"""
    adapter = HttpJavaDataAdapter(base_url=None)
    obs = await adapter.execute("portfolio.delete_positions", {})
    assert obs.status == "FAILED"
    assert obs.error_code == "JAVA_UNAVAILABLE"


@pytest.mark.asyncio
async def test_java_adapter_returns_risk_profile():
    """风控画像能力返回默认 mock。"""
    adapter = HttpJavaDataAdapter(base_url=None)
    obs = await adapter.execute("user.get_risk_profile", {"user_id": "u1"})
    assert obs.status == "SUCCESS"
    assert obs.data["risk_tolerance"] == "moderate"


@pytest.mark.asyncio
async def test_java_adapter_production_no_mock_degration():
    """生产环境（production=True）无 Java 服务 → UNAVAILABLE，不伪造 mock（审查 §5.3）。"""
    adapter = HttpJavaDataAdapter(base_url=None, production=True)
    obs = await adapter.execute("portfolio.get_current_positions", {"user_id": "u1"})
    assert obs.status == "UNAVAILABLE"
    assert obs.data is None
    assert "portfolio.get_current_positions" in obs.data_quality.known_unavailable


@pytest.mark.asyncio
async def test_java_adapter_uses_explicit_path_not_capability():
    """URL 使用显式契约路径而非拼 capability（审查 §5.3）。"""
    from stockwise_analysis.tools.java_data_adapter import _JAVA_API_PATHS

    assert _JAVA_API_PATHS["portfolio.get_current_positions"] == "/api/portfolio/positions"
    assert "portfolio.get_current_positions" not in _JAVA_API_PATHS["portfolio.get_current_positions"]
