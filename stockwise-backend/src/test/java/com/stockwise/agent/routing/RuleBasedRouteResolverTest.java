package com.stockwise.agent.routing;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 验证确定性规则只处理能够唯一决定执行路径的高置信请求。
 */
class RuleBasedRouteResolverTest {

    private final SectorEntityResolver sectorResolver = new SectorEntityResolver();
    private final DeterministicEntityExtractor entityExtractor = new DeterministicEntityExtractor();
    private final RuleBasedRouteResolver resolver = new RuleBasedRouteResolver(sectorResolver);
    private final DeterministicRouteValidator validator = new DeterministicRouteValidator(
            new RouteExecutionPolicyRegistry(), sectorResolver);

    @Test
    void priceQuestionRoutesToMarketFact() {
        RouteDecision decision = route("600519现在多少钱", null);

        assertEquals(RequestRoute.MARKET_FACT, decision.route());
        assertEquals(ModelPolicy.TEMPLATE_ONLY, decision.modelPolicy());
        assertEquals("600519", decision.symbol());
    }

    @Test
    void causalQuestionRequiresSkillAndExternalEvidence() {
        RouteDecision decision = route("600519受最新政策影响会利好吗", null);

        assertEquals(RequestRoute.MARKET_CAUSAL_ANALYSIS, decision.route());
        assertTrue(decision.requiresMarketData());
        assertTrue(decision.requiresExternalEvidence());
        assertEquals(RouteSubjectType.STOCK, decision.subjectType());
    }

    @Test
    void macroSectorCausalQuestionUsesSectorSubject() {
        RouteDecision decision = route("央行降息对银行股有什么影响", null);

        assertEquals(RequestRoute.MARKET_CAUSAL_ANALYSIS, decision.route());
        assertEquals(RouteSubjectType.SECTOR, decision.subjectType());
        assertEquals(SectorType.INDUSTRY, decision.sectorType());
        assertTrue(decision.sectors().contains("银行"));
    }

    @Test
    void sectorDirectionQuestionUsesDedicatedRoute() {
        RouteDecision decision = route("新能源车是不是到顶了", null);

        assertEquals(RequestRoute.SECTOR_ANALYSIS, decision.route());
        assertEquals(SectorType.CONCEPT, decision.sectorType());
        assertTrue(decision.sectors().contains("新能源车"));
    }

    @Test
    void overallSectorRankingDoesNotRequireSpecificSectorName() {
        RouteDecision decision = route("今天哪些板块最强", null);

        assertEquals(RequestRoute.SECTOR_FACT, decision.route());
        assertEquals(RouteSubjectType.MARKET, decision.subjectType());
        assertEquals(SectorType.INDUSTRY, decision.sectorType());
        assertTrue(decision.sectors().isEmpty());
    }

    @Test
    void sectorAttentionUsesLocalEvidenceRoute() {
        RouteDecision decision = route("半导体板块最近网上讨论度高吗", null);

        assertEquals(RequestRoute.SECTOR_ATTENTION, decision.route());
        assertEquals(ModelPolicy.LOCAL_ONLY, decision.modelPolicy());
        assertTrue(decision.requiresExternalEvidence());
    }

    @Test
    void macdExplanationStaysLocal() {
        RouteDecision decision = route("什么是MACD", null);

        assertEquals(RequestRoute.KNOWLEDGE_QA, decision.route());
        assertEquals(ModelPolicy.LOCAL_ONLY, decision.modelPolicy());
        assertFalse(decision.requiresMarketData());
    }

    @Test
    void symbolIndicatorQuestionUsesTemplateOnly() {
        RouteDecision decision = route("600519的MACD是多少", null);

        assertEquals(RequestRoute.MARKET_FACT, decision.route());
        assertEquals(ModelPolicy.TEMPLATE_ONLY, decision.modelPolicy());
        assertEquals("600519", decision.symbol());
    }

    @Test
    void selectedInstrumentSuppliesMissingSymbol() {
        RouteDecision decision = route("现在适合买入吗", "600519");

        assertEquals(RequestRoute.STOCK_DECISION, decision.route());
        assertEquals("600519", decision.symbol());
    }

    @Test
    void explicitSymbolOverridesSelectedInstrument() {
        RouteDecision decision = route("000001现在多少钱", "600519");

        assertEquals(RequestRoute.MARKET_FACT, decision.route());
        assertEquals("000001", decision.symbol());
    }

    @Test
    void bareSymbolAbstainsInsteadOfBecomingPaidAnalysis() {
        RoutingContext context = entityExtractor.extract("帮我看看600519", null, true);

        assertTrue(resolver.resolve(context).isEmpty());
    }

    private RouteDecision route(String question, String contextSymbol) {
        RoutingContext context = entityExtractor.extract(question, contextSymbol, true);
        return validator.validate(context, resolver.resolve(context).orElseThrow());
    }
}
