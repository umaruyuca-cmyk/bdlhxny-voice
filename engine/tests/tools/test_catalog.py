"""统一工具目录单测（WO-T2-1）。

覆盖：ToolCard 字段完整性、危险动作语义物理守卫、read_only 红线、
MCP 工具代理登记、scope 可见性过滤、自 CapabilityRegistry 迁移、
双目的 description、记忆召回伴侣工具、pydantic 参数投影。
数据源：conftest 的 seeded registry_snapshot（与引擎工具注册表种子语义一致）。
"""

from __future__ import annotations

import pytest

from bdlh_runtime.tools.catalog import (
    CostHint,
    EmptyArgs,
    SymbolArgs,
    ToolCard,
    ToolCatalog,
    ToolOrigin,
    catalog_from_snapshot,
    is_trading_semantic,
    register_mcp_tool,
)

# ── 危险动作语义守卫(金融档案) ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "trade.buy_stock",
        "portfolio.place_order",
        "market.sell_all",
        "broker.execute_order",
    ],
)
def test_trading_semantic_names_rejected(name: str, finance_pack):
    assert is_trading_semantic(name, "工具描述"), name


@pytest.mark.parametrize(
    "name",
    [
        "market.get_quote",
        "portfolio.get_current_positions",
        "analysis.run_analysis",
        "research.web_search",
    ],
)
def test_readonly_names_not_trading_semantic(name: str, finance_pack):
    assert not is_trading_semantic(name, "读取数据"), name


def test_trading_semantic_chinese_description_rejected(finance_pack):
    """CJK 无单词边界：描述中的危险动作词必须命中，不能依赖 \\b。"""
    assert is_trading_semantic("market.helper", "该工具可以买入股票")


def test_empty_dangerous_profile_allows_registration():
    """默认不加载垂直词表时，含旧交易词的描述也可注册(机制在、词表空)。"""
    from bdlh_runtime.scenarios import disable_all_scenario_packs
    from bdlh_runtime.scenarios.dangerous_actions import clear_profiles

    disable_all_scenario_packs()
    clear_profiles()
    catalog = ToolCatalog()
    catalog.register(ToolCard(name="demo.buy_hint", description="文案提到买入但不算配置拦截"))
    assert catalog.contains("demo.buy_hint")


def test_catalog_register_rejects_trading_semantic_card(finance_pack):
    catalog = ToolCatalog()
    with pytest.raises(ValueError, match="危险动作"):
        catalog.register(ToolCard(name="trade.buy", description="买入股票"))
    assert len(catalog) == 0


def test_catalog_register_rejects_readwrite_card():
    catalog = ToolCatalog()
    with pytest.raises(ValueError, match="只读"):
        catalog.register(ToolCard(name="memory.write", description="写入记忆", read_only=False))
    assert len(catalog) == 0


def test_catalog_register_rejects_duplicate():
    catalog = ToolCatalog()
    card = ToolCard(name="market.get_quote", description="行情")
    catalog.register(card)
    with pytest.raises(ValueError, match="already registered"):
        catalog.register(ToolCard(name="market.get_quote", description="行情2"))


def test_trading_history_readonly_exempt(finance_pack):
    """成交流水只读查询在豁免白名单（查询已发生记录，不承载执行）。"""
    assert not is_trading_semantic("portfolio.get_transaction_history", "读取交易历史")


# ── 自 seeded snapshot 迁移 ──────────────────────────────────────────────────


def test_catalog_from_snapshot_covers_seeded_capabilities(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    cards = catalog.list()
    seeded_names = {cap.name for cap in registry_snapshot.capabilities}
    catalog_names = {card.name for card in cards}
    assert seeded_names <= catalog_names
    assert "search_tools" in catalog_names
    assert len(cards) == len(registry_snapshot.capabilities) + 1
    for card in cards:
        assert card.read_only is True
        assert "." in card.name or card.name == "search_tools"


def test_toolcard_field_completeness(registry_snapshot, finance_pack):
    """§4.1 七字段完整：name/description/parameters/origin/read_only/required_scope/cost_hint。"""
    catalog = catalog_from_snapshot(registry_snapshot)
    quote = catalog.get("market.get_realtime_quote")
    assert quote.name == "market.get_realtime_quote"
    assert "检索关键词" in quote.description
    assert "实时报价" in quote.description
    assert quote.parameters["type"] == "object"
    assert quote.parameters["required"] == ["symbol"]
    assert quote.parameters["properties"]["symbol"]["type"] == "string"
    assert quote.origin is ToolOrigin.MCP  # adapter=mcp → origin=mcp
    assert quote.read_only is True
    assert "market_read" in quote.required_scope  # scope 自 toolsets 派生
    assert quote.cost_hint is CostHint.NORMAL


def test_authenticated_tools_carry_identity_scope(registry_snapshot):
    """requires_authenticated_user 的能力带 authenticated 身份标签。"""
    catalog = catalog_from_snapshot(registry_snapshot)
    positions = catalog.get("portfolio.get_current_positions")
    assert "authenticated" in positions.required_scope
    assert positions.origin is ToolOrigin.LOCAL  # adapter=java → origin=local


def test_deep_search_is_premium(registry_snapshot):
    """深度研究 premium（§4.3 G-γ），其余 normal。"""
    catalog = catalog_from_snapshot(registry_snapshot)
    assert catalog.get("research.deep_search").cost_hint is CostHint.PREMIUM
    assert catalog.get("market.get_realtime_quote").cost_hint is CostHint.NORMAL


def test_scope_visibility_filter(registry_snapshot):
    """list_visible：scope 命中可见；空 required_scope 全场景可见。"""
    catalog = catalog_from_snapshot(registry_snapshot)
    market_only = catalog.list_visible({"market_read"})
    names = {c.name for c in market_only}
    assert "market.get_realtime_quote" in names
    assert "portfolio.get_current_positions" not in names  # portfolio_read 未授
    with_auth = catalog.list_visible({"portfolio_read", "authenticated"})
    assert any(c.name == "portfolio.get_current_positions" for c in with_auth)


def test_dual_purpose_descriptions_cover_catalog(registry_snapshot, finance_pack):
    """启用场景包后，垂直工具也具备双目的 description；通用工具始终具备。"""
    catalog = catalog_from_snapshot(registry_snapshot)
    for card in catalog.list():
        assert "检索关键词" in card.description, card.name
        assert not is_trading_semantic(card.name, card.description), card.name


def test_tool_categories_present(registry_snapshot):
    """通用分析/检索与垂直能力均登记在目录(垂直场景装载仍依赖场景包)。"""
    catalog = catalog_from_snapshot(registry_snapshot)
    names = {card.name for card in catalog.list()}
    assert "market.get_realtime_quote" in names
    assert "portfolio.get_current_positions" in names
    assert "user.get_risk_profile" in names
    assert "analysis.run_analysis" in names
    assert "research.web_search" in names
    assert catalog.get("market.get_realtime_quote").origin is ToolOrigin.MCP
    assert catalog.get("research.web_search").origin is ToolOrigin.LOCAL


def test_parameters_projected_from_pydantic(registry_snapshot):
    """本地/MCP 参数 schema 由 pydantic 契约投影，而非手写 dict。"""
    catalog = catalog_from_snapshot(registry_snapshot)
    expected_quote = SymbolArgs.model_json_schema()
    expected_quote.pop("title", None)
    assert catalog.get("market.get_realtime_quote").parameters == expected_quote
    history = catalog.get("market.get_historical_prices").parameters
    assert set(history["required"]) == {"lookback_days", "symbol"}
    assert history["properties"]["lookback_days"]["minimum"] == 1
    empty = catalog.get("portfolio.get_current_positions").parameters
    assert empty["properties"] == EmptyArgs.model_json_schema()["properties"]
    search = catalog.get("search_tools").parameters
    assert search["required"] == ["query"]
    assert "top_k" in search["properties"]
    assert "top_k" not in search["required"]


def test_manifest_omits_governance_fields(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    manifest = catalog.get("market.get_realtime_quote").manifest()
    assert set(manifest) == {"name", "description", "parameters"}
    assert "origin" not in manifest
    assert "cost_hint" not in manifest


def test_snapshot_catalog_has_no_trading_tools(registry_snapshot, finance_pack):
    catalog = catalog_from_snapshot(registry_snapshot)
    for card in catalog.list():
        assert card.read_only is True
        assert not is_trading_semantic(card.name, card.description)


# ── MCP 工具代理登记（C-5）────────────────────────────────────────────────────


def test_register_mcp_tool_proxy(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    before = len(catalog)
    card = register_mcp_tool(
        catalog,
        name="weather.get_forecast",
        description="查询城市天气预报（可插拔性实证：非垂直域 MCP 工具）",
        parameters={"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
        required_scope=["weather_read"],
    )
    assert card.origin is ToolOrigin.MCP
    assert len(catalog) == before + 1
    assert catalog.contains("weather.get_forecast")


def test_mcp_tool_same_governance_as_local(registry_snapshot, finance_pack):
    """治理对本地与 MCP 工具一致生效：危险动作守卫同样拦截 MCP 登记。

    注：``register_mcp_tool`` 恒定 ``read_only=True``（MCP 代理登记不允许写语义），
    只读红线的拒绝路径由 ``test_catalog_register_rejects_readwrite_card`` 覆盖。
    """
    catalog = catalog_from_snapshot(registry_snapshot)
    with pytest.raises(ValueError, match="危险动作"):
        register_mcp_tool(catalog, name="broker.mcp_buy", description="经 MCP 买入")


def test_generic_order_status_readonly_exempt(finance_pack):
    """GT-6 通用目录的 order.get_status(只读订单查询)不被名字守卫误拦。"""
    assert not is_trading_semantic("order.get_status", "查询订单状态")
    assert is_trading_semantic("order.place_order", "下单")  # 真执行语义仍拦截
