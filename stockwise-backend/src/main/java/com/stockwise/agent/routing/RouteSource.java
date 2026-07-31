package com.stockwise.agent.routing;

/**
 * 记录路由候选的判定来源，用于审计命中率、降级率和模型漂移。
 */
public enum RouteSource {
    REGEX,
    DEEPSEEK,
    LOCAL_FALLBACK,
    CLARIFICATION
}
