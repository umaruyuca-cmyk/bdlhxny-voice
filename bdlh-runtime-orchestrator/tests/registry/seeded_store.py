"""测试共享：构建与种子迁移行语义一致的 InMemoryRegistryStore。

行内容必须与根目录数据库种子 ``db/postgresql/seed/registry.sql``
保持一致——本 helper 同时承担「种子语义」的回归校验职责。
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bdlh_runtime.registry import (  # noqa: E402
    CapabilityRecord,
    InMemoryRegistryStore,
    OperationRecord,
    SkillRecord,
    ToolsetRecord,
)
from bdlh_runtime.registry.defaults import (  # noqa: E402
    DEFAULT_ENTITLEMENT_OPERATIONS,
    DEFAULT_RUNTIME_ALLOWED_OPERATIONS,
)

OPERATIONS = [
    ("READ_MARKET_DATA", "读取公开市场数据"),
    ("READ_PUBLIC_RESEARCH", "读取外部公开研究资料"),
    ("READ_PORTFOLIO", "读取用户持仓与账户"),
    ("READ_PROFILE", "读取用户风险画像"),
    ("READ_FINANCIAL_GOALS", "读取用户财务目标"),
    ("RUN_ANALYSIS", "执行确定性金融分析"),
    ("PROPOSE_TASK", "提议持续观察任务"),
]

TOOLSETS = [
    ("market_read", "读取标的、行情、历史价格和资金流数据"),
    ("fundamental_read", "读取财务报表、估值和行业背景数据"),
    ("news_read", "读取结构化新闻和外部公开资料"),
    ("portfolio_read", "只读访问当前用户持仓、账户和交易历史"),
    ("financial_profile_read", "只读访问当前用户风险画像和金融档案"),
    ("planning_compute", "对标准化数据执行确定性金融计算"),
]

# 能力名, 适配器, 是否需登录用户, depends_on, 操作证, toolsets
CAPABILITIES = [
    ("market.resolve_instrument", "mcp", False, frozenset(), {"READ_MARKET_DATA"}, {"market_read"}),
    ("market.get_realtime_quote", "mcp", False, {"market.resolve_instrument"}, {"READ_MARKET_DATA"}, {"market_read"}),
    (
        "market.get_historical_prices",
        "mcp",
        False,
        {"market.resolve_instrument"},
        {"READ_MARKET_DATA"},
        {"market_read"},
    ),
    (
        "market.get_financial_statements",
        "mcp",
        False,
        {"market.resolve_instrument"},
        {"READ_MARKET_DATA"},
        {"fundamental_read"},
    ),
    ("market.get_valuation", "mcp", False, {"market.resolve_instrument"}, {"READ_MARKET_DATA"}, {"fundamental_read"}),
    (
        "market.get_industry_context",
        "mcp",
        False,
        {"market.resolve_instrument"},
        {"READ_MARKET_DATA"},
        {"fundamental_read"},
    ),
    ("market.get_money_flow", "mcp", False, {"market.resolve_instrument"}, {"READ_MARKET_DATA"}, {"market_read"}),
    ("market.get_news", "mcp", False, {"market.resolve_instrument"}, {"READ_MARKET_DATA"}, {"news_read"}),
    ("research.web_search", "web", False, frozenset(), {"READ_PUBLIC_RESEARCH"}, {"news_read"}),
    ("research.deep_search", "local", False, frozenset(), {"READ_PUBLIC_RESEARCH"}, {"news_read"}),
    ("analysis.run_analysis", "local", False, frozenset(), {"RUN_ANALYSIS"}, {"planning_compute"}),
    ("portfolio.get_current_positions", "java", True, frozenset(), {"READ_PORTFOLIO"}, {"portfolio_read"}),
    ("portfolio.get_account_snapshot", "java", True, frozenset(), {"READ_PORTFOLIO"}, {"portfolio_read"}),
    ("portfolio.get_transaction_history", "java", True, frozenset(), {"READ_PORTFOLIO"}, {"portfolio_read"}),
    (
        "portfolio.build_current_valuation",
        "local",
        True,
        {"portfolio.get_current_positions", "portfolio.get_account_snapshot"},
        {"READ_PORTFOLIO"},
        {"portfolio_read"},
    ),
    ("user.get_risk_profile", "java", True, frozenset(), {"READ_PROFILE"}, {"financial_profile_read"}),
]

DEFAULT_RUNTIME_ALLOWLIST = set(DEFAULT_RUNTIME_ALLOWED_OPERATIONS)
DEFAULT_ENTITLEMENTS = set(DEFAULT_ENTITLEMENT_OPERATIONS)

STOCK_RESEARCH_CAPS = [
    "market.resolve_instrument",
    "market.get_realtime_quote",
    "market.get_historical_prices",
    "market.get_financial_statements",
    "market.get_valuation",
    "market.get_industry_context",
    "market.get_money_flow",
    "market.get_news",
    "analysis.run_analysis",
]
PORTFOLIO_HEALTH_CAPS = [
    "portfolio.get_current_positions",
    "portfolio.get_account_snapshot",
    "portfolio.build_current_valuation",
    "user.get_risk_profile",
]
SUITABILITY_CAPS = [
    "market.resolve_instrument",
    "market.get_realtime_quote",
    "market.get_financial_statements",
    "market.get_valuation",
    "analysis.run_analysis",
    "portfolio.get_current_positions",
    "portfolio.get_account_snapshot",
    "portfolio.build_current_valuation",
    "user.get_risk_profile",
]


def build_seeded_store() -> InMemoryRegistryStore:
    """构建与业务种子行语义一致的内存仓储（默认只启用 stock-research）。"""
    store = InMemoryRegistryStore()
    store.operations = [OperationRecord(code, desc) for code, desc in OPERATIONS]
    store.toolsets = [ToolsetRecord(name, desc) for name, desc in TOOLSETS]
    store.capabilities = [
        CapabilityRecord(
            name=name,
            description=f"{name} description",
            domain=name.split(".")[0],
            adapter=adapter,
            read_only=True,
            requires_authenticated_user=needs_auth,
            required_arguments=frozenset(),
            depends_on=frozenset(depends),
            timeout_seconds=20,
            enabled=True,
            operations=frozenset(ops),
            toolsets=frozenset(toolsets),
        )
        for name, adapter, needs_auth, depends, ops, toolsets in CAPABILITIES
    ]
    store.skills = [
        SkillRecord(
            skill_id="stock-research",
            skill_version="1.0.0",
            domain="finance",
            status="CURRENT",
            enabled=True,
            operations=frozenset(
                {
                    ("READ_MARKET_DATA", True),
                    ("RUN_ANALYSIS", True),
                    ("READ_PUBLIC_RESEARCH", False),
                }
            ),
            capabilities=frozenset(
                {(name, name not in {"research.web_search", "research.deep_search"}) for name in STOCK_RESEARCH_CAPS}
                | {("research.web_search", False), ("research.deep_search", False)}
            ),
        ),
        SkillRecord(
            skill_id="portfolio-health",
            skill_version="1.0.0",
            domain="finance",
            status="CURRENT",
            enabled=True,
            operations=frozenset(
                {
                    ("READ_PORTFOLIO", True),
                    ("READ_PROFILE", True),
                    ("READ_FINANCIAL_GOALS", False),
                    ("READ_MARKET_DATA", False),
                }
            ),
            capabilities=frozenset((name, True) for name in PORTFOLIO_HEALTH_CAPS),
        ),
        SkillRecord(
            skill_id="suitability-evaluation",
            skill_version="1.0.0",
            domain="finance",
            status="FOUNDATION",
            enabled=False,
            operations=frozenset(
                {
                    ("READ_MARKET_DATA", True),
                    ("READ_PORTFOLIO", True),
                    ("READ_PROFILE", True),
                    ("RUN_ANALYSIS", True),
                    ("READ_PUBLIC_RESEARCH", False),
                }
            ),
            capabilities=frozenset(
                {
                    *(
                        (name, name not in {"research.web_search", "research.deep_search"})
                        for name in SUITABILITY_CAPS
                    ),
                    ("research.web_search", False),
                    ("research.deep_search", False),
                }
            ),
        ),
    ]
    return store
