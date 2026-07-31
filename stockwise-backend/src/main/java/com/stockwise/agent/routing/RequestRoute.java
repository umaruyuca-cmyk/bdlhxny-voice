package com.stockwise.agent.routing;

/**
 * 表示一次用户请求的最终执行路径，用于替代粗粒度 Intent 直接选择 Skill。
 */
public enum RequestRoute {
    GENERAL_CHAT,
    KNOWLEDGE_QA,
    EXTERNAL_RESEARCH,
    MARKET_FACT,
    SECTOR_FACT,
    SECTOR_ATTENTION,
    STOCK_DECISION,
    PORTFOLIO_DECISION,
    QUANT_DECISION,
    SECTOR_ANALYSIS,
    MARKET_CAUSAL_ANALYSIS,
    NEED_CLARIFICATION
}
