"""组合影响分析测试（Phase 4）。"""

from __future__ import annotations

import pytest

from bdlh_runtime.contracts.analysis import AnalysisInput
from bdlh_runtime.contracts.observation import DataQuality
from bdlh_runtime.domain.analysis_engine import analyze
from bdlh_runtime.tools.java_data_adapter import (
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
    assert obs.data["user_id"] == "u1"
    assert obs.data["data_mode"] == "MOCK"


@pytest.mark.asyncio
async def test_java_adapter_production_no_mock_degration():
    """生产环境（production=True）无 Java 服务 → UNAVAILABLE，不伪造 mock（审查 §5.3）。"""
    adapter = HttpJavaDataAdapter(base_url=None, production=True)
    obs = await adapter.execute("portfolio.get_current_positions", {"user_id": "u1"})
    assert obs.status == "UNAVAILABLE"
    assert obs.data is None
    assert "portfolio.get_current_positions" in obs.data_quality.known_unavailable
    assert obs.provenance and obs.provenance[0].source == "java-api"


@pytest.mark.asyncio
async def test_java_adapter_uses_explicit_path_not_capability():
    """URL 使用显式契约路径而非拼 capability（审查 §5.3）。"""
    from bdlh_runtime.tools.java_data_adapter import _JAVA_API_PATHS

    assert _JAVA_API_PATHS["portfolio.get_current_positions"] == "/api/portfolio/positions"
    assert "portfolio.get_current_positions" not in _JAVA_API_PATHS["portfolio.get_current_positions"]


@pytest.mark.asyncio
async def test_java_adapter_consumes_snake_case_contract(monkeypatch):
    """Java Data API 的 snake_case DTO 可被 Python 原样消费并保留数据时间。"""
    import httpx

    captured_headers = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "metadata": {
                    "schema_version": "financial-user-data.v2",
                    "user_id": 7,
                    "authorization_scope": "SELF",
                    "data_mode": "USER_CONFIRMED",
                    "source_type": "USER_INPUT",
                    "query_status": "SUCCESS",
                    "data_time": "2026-08-09T00:00:00Z",
                    "confirmation_ref": "confirm-positions-1",
                    "missing_fields": [],
                },
                "positions": [{
                    "symbol": "600519",
                    "exchange": "SSE",
                    "currency": "CNY",
                    "quantity": 100,
                    "cost_price": 1500,
                }],
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, *_args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    adapter = HttpJavaDataAdapter(base_url="http://java-data", token="internal-secret")

    obs = await adapter.execute("portfolio.get_current_positions", {"user_id": 7})

    assert obs.status == "SUCCESS"
    assert obs.data["positions"][0]["cost_price"] == 1500
    assert obs.data["metadata"]["data_mode"] == "USER_CONFIRMED"
    assert obs.data["metadata"]["confirmation_ref"] == "confirm-positions-1"
    assert obs.provenance[0].as_of == "2026-08-09T00:00:00Z"
    assert captured_headers == {"X-Internal-Token": "internal-secret"}


@pytest.mark.asyncio
async def test_java_adapter_does_not_mock_a_configured_but_failed_service(monkeypatch):
    """配置了真实 Java 地址后，调用失败不能静默伪造成 mock 持仓。"""
    import httpx

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, *_args, **_kwargs):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: FailingClient())
    adapter = HttpJavaDataAdapter(base_url="http://java-data", production=False)

    obs = await adapter.execute("portfolio.get_current_positions", {"user_id": 7})

    assert obs.status == "UNAVAILABLE"
    assert obs.data is None


@pytest.mark.asyncio
async def test_java_adapter_propagates_not_configured_status(monkeypatch):
    """Java 明确返回未配置时，Python 不得把空风险画像标记为成功。"""
    import httpx

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"metadata": {"query_status": "NOT_CONFIGURED"}, "risk_tolerance": None}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    adapter = HttpJavaDataAdapter(base_url="http://java-data")

    obs = await adapter.execute("user.get_risk_profile", {"user_id": 7})

    assert obs.status == "PARTIAL"
    assert obs.error_code == "JAVA_DATA_NOT_CONFIGURED"
