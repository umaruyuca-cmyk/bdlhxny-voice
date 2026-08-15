package com.bdlh.runtime.agent.routing;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 验证 Route-Intent-Skill 映射不会把事实查询和外部搜索升级为付费调用。
 */
class RouteExecutionPolicyRegistryTest {

    private final RouteExecutionPolicyRegistry registry = new RouteExecutionPolicyRegistry();

    @Test
    void marketFactOnlyAllowsStockCommandAndTemplate() {
        RouteExecutionPolicy policy = registry.get(RequestRoute.MARKET_FACT);

        assertEquals(ModelPolicy.TEMPLATE_ONLY, policy.modelPolicy());
        assertTrue(registry.allowsCommand(RequestRoute.MARKET_FACT, "stock"));
        assertFalse(registry.allowsCommand(RequestRoute.MARKET_FACT, "quant"));
    }

    @Test
    void externalResearchDoesNotAllowFinancialSkill() {
        RouteExecutionPolicy policy = registry.get(RequestRoute.EXTERNAL_RESEARCH);

        assertEquals(ModelPolicy.LOCAL_ONLY, policy.modelPolicy());
        assertTrue(policy.webSearchRequired());
        assertTrue(policy.allowedSkillCommands().isEmpty());
    }

    @Test
    void sectorAndQuantRoutesOwnDifferentCommands() {
        assertTrue(registry.allowsCommand(RequestRoute.SECTOR_ANALYSIS, "sector"));
        assertFalse(registry.allowsCommand(RequestRoute.SECTOR_ANALYSIS, "quant"));
        assertTrue(registry.allowsCommand(RequestRoute.QUANT_DECISION, "quant"));
        assertFalse(registry.allowsCommand(RequestRoute.QUANT_DECISION, "sector"));
    }

    @Test
    void causalRouteAllowsSubjectSpecificMarketCommandAndRequiresSearch() {
        RouteExecutionPolicy policy = registry.get(RequestRoute.MARKET_CAUSAL_ANALYSIS);

        assertTrue(registry.allowsCommand(RequestRoute.MARKET_CAUSAL_ANALYSIS, "stock"));
        assertTrue(registry.allowsCommand(RequestRoute.MARKET_CAUSAL_ANALYSIS, "sector"));
        assertTrue(policy.webSearchRequired());
    }
}
