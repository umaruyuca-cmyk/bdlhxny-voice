"""Suitability v0 运行时规则集（内部启发式，非法定适当性）。

阈值来自 ADR-004 §6 推荐草案，以 ``status=DRAFT`` 装配进代码，便于迭代。
改阈值走 PR；不要求 ADR 签署栏才能运行。
"""

from __future__ import annotations

from bdlh_runtime.domains.finance.contracts import (
    ConcentrationThreshold,
    MarketRiskProxyThresholds,
    SuitabilityV0RuleSet,
)

RULE_IDS: tuple[str, ...] = (
    "SUIT-RESEARCH-COVERAGE-001",
    "SUIT-DATA-AUTHENTICITY-001",
    "SUIT-RISK-LEVEL-001",
    "SUIT-MAX-LOSS-001",
    "SUIT-CONCENTRATION-001",
    "SUIT-LIQUIDITY-001",
    "SUIT-GOAL-HORIZON-001",
)

CRITICAL_RULE_IDS = frozenset(RULE_IDS[:-1])  # GOAL 非关键


def default_suitability_v0_rule_set() -> SuitabilityV0RuleSet:
    """返回当前 Runtime 使用的 v0 规则集。"""

    return SuitabilityV0RuleSet(
        version="suitability-v0.1",
        status="DRAFT",
        rule_ids=list(RULE_IDS),
        critical_rule_ids=set(CRITICAL_RULE_IDS),
        market_risk_proxy_thresholds=MarketRiskProxyThresholds(
            medium_max_drawdown_pct=20,
            high_max_drawdown_pct=40,
            medium_annualized_volatility_pct=20,
            high_annualized_volatility_pct=35,
            minimum_observation_count=20,
            annualization_trading_days=244,
            price_adjustment="FORWARD",
        ),
        single_position_thresholds={
            "CONSERVATIVE": ConcentrationThreshold(conditional_above_pct=15, block_above_pct=20),
            "BALANCED": ConcentrationThreshold(conditional_above_pct=20, block_above_pct=30),
            "AGGRESSIVE": ConcentrationThreshold(conditional_above_pct=30, block_above_pct=40),
        },
        industry_thresholds={
            "CONSERVATIVE": ConcentrationThreshold(conditional_above_pct=30, block_above_pct=40),
            "BALANCED": ConcentrationThreshold(conditional_above_pct=40, block_above_pct=50),
            "AGGRESSIVE": ConcentrationThreshold(conditional_above_pct=50, block_above_pct=60),
        },
        liquidity_pass_buffer_ratio=1.2,
    )
