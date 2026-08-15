package com.bdlh.runtime.agent.routing;

import com.bdlh.runtime.llm.ChatIntent;
import org.springframework.stereotype.Component;

import java.util.EnumMap;
import java.util.Map;
import java.util.Set;

/**
 * 集中维护 Route-Intent-Skill 映射，防止 Prompt 或模型动态扩大工具权限。
 */
@Component
public class RouteExecutionPolicyRegistry {

    private final Map<RequestRoute, RouteExecutionPolicy> policies;

    public RouteExecutionPolicyRegistry() {
        EnumMap<RequestRoute, RouteExecutionPolicy> values = new EnumMap<>(RequestRoute.class);
        values.put(RequestRoute.GENERAL_CHAT, policy(
                RequestRoute.GENERAL_CHAT, ChatIntent.GENERAL_CHAT, ModelPolicy.LOCAL_ONLY, Set.of(), true, false));
        values.put(RequestRoute.KNOWLEDGE_QA, policy(
                RequestRoute.KNOWLEDGE_QA, ChatIntent.INVESTMENT_QA, ModelPolicy.LOCAL_ONLY, Set.of(), false, false));
        values.put(RequestRoute.EXTERNAL_RESEARCH, policy(
                RequestRoute.EXTERNAL_RESEARCH, ChatIntent.INVESTMENT_QA, ModelPolicy.LOCAL_ONLY, Set.of(), true, true));
        values.put(RequestRoute.MARKET_FACT, policy(
                RequestRoute.MARKET_FACT, ChatIntent.STOCK_ANALYSIS, ModelPolicy.TEMPLATE_ONLY,
                Set.of("stock"), false, false));
        values.put(RequestRoute.SECTOR_FACT, policy(
                RequestRoute.SECTOR_FACT, ChatIntent.STOCK_ANALYSIS, ModelPolicy.TEMPLATE_ONLY,
                Set.of("sector"), false, false));
        values.put(RequestRoute.SECTOR_ATTENTION, policy(
                RequestRoute.SECTOR_ATTENTION, ChatIntent.STOCK_ANALYSIS, ModelPolicy.LOCAL_ONLY,
                Set.of("sector"), true, true));
        values.put(RequestRoute.STOCK_DECISION, policy(
                RequestRoute.STOCK_DECISION, ChatIntent.STOCK_ANALYSIS, ModelPolicy.PAID_AFTER_VALIDATED_SKILL,
                Set.of("stock"), false, false));
        values.put(RequestRoute.PORTFOLIO_DECISION, policy(
                RequestRoute.PORTFOLIO_DECISION, ChatIntent.PORTFOLIO_ANALYSIS,
                ModelPolicy.PAID_AFTER_VALIDATED_SKILL, Set.of("portfolio", "stock"), false, false));
        values.put(RequestRoute.QUANT_DECISION, policy(
                RequestRoute.QUANT_DECISION, ChatIntent.PORTFOLIO_ANALYSIS,
                ModelPolicy.PAID_AFTER_VALIDATED_SKILL, Set.of("quant"), false, false));
        values.put(RequestRoute.SECTOR_ANALYSIS, policy(
                RequestRoute.SECTOR_ANALYSIS, ChatIntent.PORTFOLIO_ANALYSIS,
                ModelPolicy.PAID_AFTER_VALIDATED_SKILL, Set.of("sector"), false, false));
        values.put(RequestRoute.MARKET_CAUSAL_ANALYSIS, policy(
                RequestRoute.MARKET_CAUSAL_ANALYSIS, ChatIntent.STOCK_ANALYSIS,
                ModelPolicy.PAID_AFTER_VALIDATED_SKILL, Set.of("stock", "sector"), true, true));
        values.put(RequestRoute.NEED_CLARIFICATION, policy(
                RequestRoute.NEED_CLARIFICATION, ChatIntent.GENERAL_CHAT,
                ModelPolicy.TEMPLATE_ONLY, Set.of(), false, false));
        this.policies = Map.copyOf(values);
    }

    /**
     * 返回指定 Route 的固定执行策略。
     */
    public RouteExecutionPolicy get(RequestRoute route) {
        RouteExecutionPolicy policy = policies.get(route);
        if (policy == null) {
            throw new IllegalArgumentException("未配置 Route 执行策略: " + route);
        }
        return policy;
    }

    /**
     * 校验 Route 是否允许执行真实 Skill Command。
     */
    public boolean allowsCommand(RequestRoute route, String command) {
        return command != null && get(route).allowedSkillCommands().contains(command);
    }

    /**
     * 校验 ReAct Action 是否属于初始 Route 的固定能力集合。
     */
    public boolean allowsAction(RequestRoute route, String actionName) {
        if (allowsCommand(route, actionName)) {
            return true;
        }
        RouteExecutionPolicy policy = get(route);
        if ("webSearch".equals(actionName)) {
            return policy.webSearchAllowed();
        }
        return (route == RequestRoute.GENERAL_CHAT || route == RequestRoute.KNOWLEDGE_QA)
                && "searchInvestmentKnowledge".equals(actionName);
    }

    private RouteExecutionPolicy policy(RequestRoute route,
                                        ChatIntent intent,
                                        ModelPolicy modelPolicy,
                                        Set<String> commands,
                                        boolean webSearchAllowed,
                                        boolean webSearchRequired) {
        return new RouteExecutionPolicy(
                route, intent, modelPolicy, Set.copyOf(commands), webSearchAllowed, webSearchRequired);
    }
}
