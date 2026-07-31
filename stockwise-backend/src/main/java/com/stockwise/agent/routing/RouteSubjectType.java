package com.stockwise.agent.routing;

/**
 * 描述路由所针对的市场主体，用于收紧本轮唯一允许的执行计划。
 */
public enum RouteSubjectType {
    NONE,
    STOCK,
    ETF_POOL,
    SECTOR,
    PORTFOLIO,
    MARKET
}
