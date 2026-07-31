package com.stockwise.agent.routing;

/**
 * 定义语义候选分类边界，便于使用固定用途的外部模型并在测试中隔离网络。
 */
public interface SemanticRouteClassifier {

    /**
     * 根据最小化路由上下文返回候选分类状态。
     */
    ClassificationResult classify(RoutingContext context);
}
