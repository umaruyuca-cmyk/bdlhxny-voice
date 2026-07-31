package com.stockwise.agent.routing;

import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 根据最终 Route 和主体类型生成唯一执行计划，把 Route 最大权限收紧为本轮 Action。
 */
@Component
public class ExecutionPlanFactory {

    /**
     * 生成不会超出 RouteExecutionPolicyRegistry 白名单的本轮 Action 集合。
     */
    public ExecutionPlan create(RouteDecision decision) {
        List<String> actions = switch (decision.route()) {
            case GENERAL_CHAT, NEED_CLARIFICATION -> List.of();
            case KNOWLEDGE_QA -> List.of("searchInvestmentKnowledge");
            case EXTERNAL_RESEARCH -> List.of("webSearch");
            case MARKET_FACT, STOCK_DECISION -> List.of("stock");
            case SECTOR_FACT -> List.of("sector");
            case SECTOR_ATTENTION -> List.of("sector", "webSearch");
            case PORTFOLIO_DECISION -> List.of("portfolio");
            case QUANT_DECISION -> List.of("quant");
            case SECTOR_ANALYSIS -> List.of("sector");
            case MARKET_CAUSAL_ANALYSIS -> causalActions(decision.subjectType());
        };
        return new ExecutionPlan(actions);
    }

    private List<String> causalActions(RouteSubjectType subjectType) {
        return switch (subjectType) {
            case STOCK -> List.of("stock", "webSearch");
            case SECTOR, MARKET -> List.of("sector", "webSearch");
            default -> List.of();
        };
    }
}
