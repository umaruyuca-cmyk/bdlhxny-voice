package com.stockwise.agent.routing;

import java.util.List;

/**
 * 保存由 Java 提取并校验的路由上下文，禁止模型重新生成代码和隐私字段。
 */
public record RoutingContext(
        String question,
        List<String> explicitSymbols,
        String contextSymbol,
        boolean portfolioAvailable
) {

    public RoutingContext {
        question = question == null ? "" : question;
        explicitSymbols = explicitSymbols == null ? List.of() : List.copyOf(explicitSymbols);
    }
}
