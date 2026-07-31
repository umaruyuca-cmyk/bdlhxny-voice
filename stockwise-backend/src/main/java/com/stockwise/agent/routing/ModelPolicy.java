package com.stockwise.agent.routing;

/**
 * 约束路由可以使用的最高模型等级，避免业务代码自行选择付费模型。
 */
public enum ModelPolicy {
    TEMPLATE_ONLY,
    LOCAL_ONLY,
    PAID_AFTER_VALIDATED_SKILL
}
