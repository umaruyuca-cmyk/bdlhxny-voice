"""治理中间件 G1–G7 单测（WO-T2-2）。

覆盖：幻觉工具名、只读红线、游客/机主权限、预算耗尽与 premium 加权、
参数非法、Observation 包装、审计字段、本地与 MCP 同一拦截链。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bdlh_runtime.contracts.observation import DataQuality, Observation, ProvenanceRecord
from bdlh_runtime.guardrails.contracts import GuardrailContext, GuardrailDecision
from bdlh_runtime.guardrails.middleware import GovernanceMiddleware
from bdlh_runtime.tools.catalog import (
    CostHint,
    ToolCard,
    ToolCatalog,
    ToolOrigin,
    catalog_from_snapshot,
)


def _context(**overrides) -> GuardrailContext:
    payload = {
        "run_id": "run-1",
        "authenticated_user_id": "user-1",
        "read_only": True,
        "max_tool_calls": 6,
    }
    payload.update(overrides)
    return GuardrailContext(**payload)


def _mw(catalog, **context_overrides) -> GovernanceMiddleware:
    return GovernanceMiddleware(catalog, context=_context(**context_overrides))


async def _ok(_name: str, arguments: dict) -> dict:
    return {"echo": arguments}


async def _boom(_name: str, _arguments: dict) -> dict:
    raise RuntimeError("upstream down")


@pytest.mark.asyncio
async def test_g1_rejects_hallucinated_tool_name(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    mw = _mw(catalog)
    loaded = {card.name for card in catalog.list_visible({"market_read"})}
    result = await mw.invoke(
        name="not.a.real_tool",
        arguments={"symbol": "300750"},
        loaded_names=loaded,
        granted_scopes={"market_read"},
        authenticated=False,
        executor=_ok,
    )
    assert result.allowed is False
    assert result.rejection.audit_code == "TOOL_NOT_VISIBLE"
    assert result.audit.status == "REJECTED"
    assert mw.remaining_budget == 6


@pytest.mark.asyncio
async def test_g1_rejects_catalog_tool_not_in_loaded_set(registry_snapshot):
    """装载集合外的真实工具名同样视为幻觉（模型不该看见）。"""
    catalog = catalog_from_snapshot(registry_snapshot)
    mw = _mw(catalog)
    result = await mw.invoke(
        name="portfolio.get_current_positions",
        arguments={},
        loaded_names={"market.get_realtime_quote"},
        granted_scopes={"market_read"},
        authenticated=True,
        executor=_ok,
    )
    assert result.rejection.audit_code == "TOOL_NOT_VISIBLE"


@pytest.mark.asyncio
async def test_g2_rejects_non_readonly_descriptor():
    card = SimpleNamespace(
        name="memory.write",
        read_only=False,
        required_scope=[],
        cost_hint="normal",
        parameters={"type": "object", "properties": {}, "required": []},
        origin="local",
    )
    catalog = SimpleNamespace(get=lambda _n: card, contains=lambda _n: True)
    mw = _mw(catalog)
    result = await mw.invoke(
        name="memory.write",
        arguments={},
        loaded_names={"memory.write"},
        granted_scopes=(),
        authenticated=True,
        executor=_ok,
    )
    assert result.rejection.audit_code == "READ_ONLY_REQUIRED"
    assert mw.remaining_budget == 6


@pytest.mark.asyncio
async def test_g3_guest_cannot_call_authenticated_tool(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    mw = _mw(catalog)
    result = await mw.invoke(
        name="portfolio.get_current_positions",
        arguments={},
        loaded_names={"portfolio.get_current_positions"},
        granted_scopes={"portfolio_read", "authenticated"},
        authenticated=False,
        executor=_ok,
    )
    assert result.rejection.audit_code == "AUTHENTICATION_REQUIRED"


@pytest.mark.asyncio
async def test_g3_scope_mismatch_denied(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    mw = _mw(catalog)
    result = await mw.invoke(
        name="market.get_realtime_quote",
        arguments={"symbol": "300750"},
        loaded_names={"market.get_realtime_quote"},
        granted_scopes={"portfolio_read"},
        authenticated=False,
        executor=_ok,
    )
    assert result.rejection.audit_code == "SCOPE_DENIED"


@pytest.mark.asyncio
async def test_g4_budget_exhausted(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    mw = _mw(catalog, max_tool_calls=1)
    first = await mw.invoke(
        name="market.get_realtime_quote",
        arguments={"symbol": "300750"},
        loaded_names={"market.get_realtime_quote"},
        granted_scopes={"market_read"},
        authenticated=False,
        executor=_ok,
    )
    assert first.allowed is True
    assert mw.remaining_budget == 0
    second = await mw.invoke(
        name="market.get_realtime_quote",
        arguments={"symbol": "600519"},
        loaded_names={"market.get_realtime_quote"},
        granted_scopes={"market_read"},
        authenticated=False,
        executor=_ok,
    )
    assert second.rejection.audit_code == "TOOL_BUDGET_EXCEEDED"
    assert second.allowed is False


@pytest.mark.asyncio
async def test_g4_premium_weighted_deduction(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    mw = _mw(catalog, max_tool_calls=3)
    result = await mw.invoke(
        name="research.deep_search",
        arguments={"question": "宁德时代近况", "objective": "梳理风险"},
        loaded_names={"research.deep_search"},
        granted_scopes={"news_read"},
        authenticated=False,
        executor=_ok,
    )
    assert result.allowed is True
    assert mw.remaining_budget == 0
    again = await mw.invoke(
        name="research.deep_search",
        arguments={"question": "再问一次", "objective": "补充"},
        loaded_names={"research.deep_search"},
        granted_scopes={"news_read"},
        authenticated=False,
        executor=_ok,
    )
    assert again.rejection.audit_code == "TOOL_BUDGET_EXCEEDED"


@pytest.mark.asyncio
async def test_g5_rejects_invalid_arguments(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    mw = _mw(catalog)
    result = await mw.invoke(
        name="market.get_realtime_quote",
        arguments={},
        loaded_names={"market.get_realtime_quote"},
        granted_scopes={"market_read"},
        authenticated=False,
        executor=_ok,
    )
    assert result.rejection.audit_code == "ARGUMENTS_INVALID"
    assert mw.remaining_budget == 6


@pytest.mark.asyncio
async def test_g6_wraps_observation_with_source_time_quality(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    mw = _mw(catalog)
    result = await mw.invoke(
        name="market.get_realtime_quote",
        arguments={"symbol": "300750"},
        loaded_names={"market.get_realtime_quote"},
        granted_scopes={"market_read"},
        authenticated=False,
        executor=_ok,
    )
    assert result.allowed is True
    obs = result.observation
    assert obs.status == "SUCCESS"
    assert obs.data == {"echo": {"symbol": "300750"}}
    assert obs.provenance[0].source == ToolOrigin.MCP
    assert obs.provenance[0].retrieved_at
    assert obs.data_quality.quality_status == "OK"


@pytest.mark.asyncio
async def test_g6_preserves_existing_observation(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    mw = _mw(catalog)

    async def already_obs(_name: str, _arguments: dict) -> Observation:
        return Observation(
            observation_id="obs-1",
            capability="market.get_realtime_quote",
            status="SUCCESS",
            data={"price": 100},
            data_quality=DataQuality(completeness=1.0, quality_status="OK"),
            provenance=[
                ProvenanceRecord(
                    source="mcp",
                    tool="market.get_realtime_quote",
                    retrieved_at="2026-08-19T00:00:00+00:00",
                )
            ],
        )

    result = await mw.invoke(
        name="market.get_realtime_quote",
        arguments={"symbol": "300750"},
        loaded_names={"market.get_realtime_quote"},
        granted_scopes={"market_read"},
        authenticated=False,
        executor=already_obs,
    )
    assert result.allowed is True
    assert result.observation.observation_id == "obs-1"
    assert result.observation.provenance[0].elapsed_ms is not None


@pytest.mark.asyncio
async def test_g6_blocks_failed_observation_via_data_quality(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    mw = _mw(catalog)

    async def failed_obs(_name: str, _arguments: dict) -> Observation:
        return Observation(
            observation_id="obs-fail",
            capability="market.get_realtime_quote",
            status="FAILED",
            data=None,
            error_code="UPSTREAM",
            error_message="源不可用",
        )

    result = await mw.invoke(
        name="market.get_realtime_quote",
        arguments={"symbol": "300750"},
        loaded_names={"market.get_realtime_quote"},
        granted_scopes={"market_read"},
        authenticated=False,
        executor=failed_obs,
    )
    assert result.allowed is False
    assert result.rejection.decision is GuardrailDecision.BLOCK
    assert result.rejection.stage.value == "data_quality"


@pytest.mark.asyncio
async def test_g7_audit_fields_on_success_and_rejection(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    mw = _mw(catalog)
    ok = await mw.invoke(
        name="market.get_realtime_quote",
        arguments={"symbol": "300750"},
        loaded_names={"market.get_realtime_quote"},
        granted_scopes={"market_read"},
        authenticated=False,
        executor=_ok,
    )
    assert ok.audit.caller == "user-1"
    assert ok.audit.tool_name == "market.get_realtime_quote"
    assert "300750" in ok.audit.arguments_summary
    assert ok.audit.status == "SUCCESS"
    assert ok.audit.audit_code is None
    assert ok.audit.elapsed_ms >= 0

    denied = await mw.invoke(
        name="ghost.tool",
        arguments={"q": "x"},
        loaded_names={"market.get_realtime_quote"},
        granted_scopes={"market_read"},
        authenticated=False,
        executor=_ok,
    )
    assert denied.audit.status == "REJECTED"
    assert denied.audit.audit_code == "TOOL_NOT_VISIBLE"
    assert len(mw.audits) == 2


@pytest.mark.asyncio
async def test_local_and_mcp_share_the_same_chain(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    mw = _mw(catalog)
    mcp = await mw.invoke(
        name="market.get_realtime_quote",
        arguments={"symbol": "300750"},
        loaded_names={"market.get_realtime_quote", "research.web_search"},
        granted_scopes={"market_read", "news_read"},
        authenticated=False,
        executor=_ok,
    )
    local = await mw.invoke(
        name="research.web_search",
        arguments={"query": "宁德时代 新闻"},
        loaded_names={"market.get_realtime_quote", "research.web_search"},
        granted_scopes={"market_read", "news_read"},
        authenticated=False,
        executor=_ok,
    )
    assert mcp.allowed and local.allowed
    assert catalog.get("market.get_realtime_quote").origin is ToolOrigin.MCP
    assert catalog.get("research.web_search").origin is ToolOrigin.LOCAL
    assert mcp.observation.provenance[0].source == "mcp"
    assert local.observation.provenance[0].source == "local"


@pytest.mark.asyncio
async def test_new_mcp_proxy_enters_chain_without_middleware_change():
    """新增 MCP 工具只需登记目录，中间件零适配。"""
    catalog = ToolCatalog()
    catalog.register(
        ToolCard(
            name="ext.get_forecast",
            description="查询公开预报。检索关键词：预报。",
            parameters={
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
                "additionalProperties": False,
            },
            origin=ToolOrigin.MCP,
            required_scope=["public_read"],
            cost_hint=CostHint.NORMAL,
        )
    )
    mw = _mw(catalog)
    result = await mw.invoke(
        name="ext.get_forecast",
        arguments={"city": "Shanghai"},
        loaded_names={"ext.get_forecast"},
        granted_scopes={"public_read"},
        authenticated=False,
        executor=_ok,
    )
    assert result.allowed is True
    assert result.observation.provenance[0].source == "mcp"


@pytest.mark.asyncio
async def test_executor_not_called_on_pre_gate_reject(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    mw = _mw(catalog)
    called = {"n": 0}

    async def tracking(name: str, arguments: dict) -> dict:
        called["n"] += 1
        return await _ok(name, arguments)

    await mw.invoke(
        name="ghost.tool",
        arguments={},
        loaded_names={"market.get_realtime_quote"},
        granted_scopes={"market_read"},
        authenticated=False,
        executor=tracking,
    )
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_executor_exception_is_structured_failure(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    mw = _mw(catalog)
    result = await mw.invoke(
        name="market.get_realtime_quote",
        arguments={"symbol": "300750"},
        loaded_names={"market.get_realtime_quote"},
        granted_scopes={"market_read"},
        authenticated=False,
        executor=_boom,
    )
    assert result.allowed is False
    assert result.audit.status == "FAILED"
    assert result.audit.audit_code == "TOOL_EXECUTION_FAILED"
    assert result.observation.status == "FAILED"
    assert mw.remaining_budget == 5
