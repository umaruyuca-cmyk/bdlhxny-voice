"""Registry 相关运行时默认（配置层单一真源；非数据库目录）。"""

from __future__ import annotations

DEFAULT_RUNTIME_ALLOWED_OPERATIONS: frozenset[str] = frozenset(
    {
        "READ_MARKET_DATA",
        "READ_PUBLIC_RESEARCH",
        "READ_PORTFOLIO",
        "READ_PROFILE",
        "READ_FINANCIAL_GOALS",
        "RUN_ANALYSIS",
    }
)

DEFAULT_ENTITLEMENT_OPERATIONS: frozenset[str] = frozenset(
    {
        "READ_MARKET_DATA",
        "READ_PUBLIC_RESEARCH",
        "READ_PORTFOLIO",
        "READ_PROFILE",
        "READ_FINANCIAL_GOALS",
        "RUN_ANALYSIS",
    }
)

DEFAULT_REACT_ROUND_LIMIT = 8
DEFAULT_TOOL_CALL_LIMIT = 12
DEFAULT_SUBGRAPH_TIMEOUT_SECONDS = 60
DEFAULT_REQUEST_TIMEOUT_SECONDS = 90
