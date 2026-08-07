package com.stockwise.agent.routing;

import com.stockwise.llm.ChatIntent;
import com.stockwise.llm.IntentClassifier;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 验证三层路由不会把语义不明确或模型不可用错误升级为付费分析。
 */
class RequestRouterTest {

    @Test
    void generalModeUsesDirectChatWithoutCallingSemanticClassifier() {
        IntentClassifier localClassifier = mock(IntentClassifier.class);
        SemanticRouteClassifier semanticClassifier = mock(SemanticRouteClassifier.class);
        RequestRouter router = router(semanticClassifier, localClassifier);

        RouteDecision decision = router.routeGeneral("解释一下什么是复利");

        assertThat(decision.route()).isEqualTo(RequestRoute.GENERAL_CHAT);
        assertThat(decision.businessRoute()).isEqualTo(BusinessRoute.DIRECT_CHAT);
        verify(semanticClassifier, never()).classify(org.mockito.ArgumentMatchers.any());
        verify(localClassifier, never()).classify(org.mockito.ArgumentMatchers.anyString());
    }

    @Test
    void generalModeUsesToolAgentForCurrentInformationEvenWhenQuestionContainsStockCode() {
        IntentClassifier localClassifier = mock(IntentClassifier.class);
        SemanticRouteClassifier semanticClassifier = mock(SemanticRouteClassifier.class);
        RequestRouter router = router(semanticClassifier, localClassifier);

        RouteDecision decision = router.routeGeneral("搜索一下600519今天的最新新闻");

        assertThat(decision.route()).isEqualTo(RequestRoute.EXTERNAL_RESEARCH);
        assertThat(decision.businessRoute()).isEqualTo(BusinessRoute.TOOL_AGENT);
        assertThat(decision.businessRoute()).isNotEqualTo(BusinessRoute.STOCK_ANALYSIS);
        verify(semanticClassifier, never()).classify(org.mockito.ArgumentMatchers.any());
    }

    @Test
    void vagueSectorAnalysisAsksForScopeInsteadOfGeneratingGenericEssay() {
        RequestRouter router = router(
                mock(SemanticRouteClassifier.class),
                mock(IntentClassifier.class));

        RouteDecision decision = router.routeGeneral("分析一下科技板块的情况");

        assertThat(decision.route()).isEqualTo(RequestRoute.NEED_CLARIFICATION);
        assertThat(decision.reasonCode()).isEqualTo("GENERAL_RESEARCH_SCOPE_REQUIRED");
        assertThat(decision.clarification()).contains("选择一个方向");
    }

    @Test
    void scopedSectorAnalysisUsesToolAgentForRealMarketEvidence() {
        RequestRouter router = router(
                mock(SemanticRouteClassifier.class),
                mock(IntentClassifier.class));

        RouteDecision decision = router.routeGeneral("复盘昨日科技板块的资金强弱");

        assertThat(decision.route()).isEqualTo(RequestRoute.EXTERNAL_RESEARCH);
        assertThat(decision.businessRoute()).isEqualTo(BusinessRoute.TOOL_AGENT);
    }

    @Test
    void stockModeAllowsCasualChatWithoutEnteringStockAnalysis() {
        IntentClassifier localClassifier = mock(IntentClassifier.class);
        SemanticRouteClassifier semanticClassifier = mock(SemanticRouteClassifier.class);
        RequestRouter router = router(semanticClassifier, localClassifier);

        RouteDecision decision = router.routeStock("你好", "600519");

        assertThat(decision.route()).isEqualTo(RequestRoute.GENERAL_CHAT);
        assertThat(decision.businessRoute()).isEqualTo(BusinessRoute.DIRECT_CHAT);
        verify(semanticClassifier, never()).classify(org.mockito.ArgumentMatchers.any());
    }

    @Test
    void stockModeRejectsAQuestionThatMentionsAnotherInstrument() {
        RequestRouter router = router(
                mock(SemanticRouteClassifier.class),
                mock(IntentClassifier.class));

        RouteDecision decision = router.routeStock("600036 现在适合买入吗", "600519");

        assertThat(decision.route()).isEqualTo(RequestRoute.NEED_CLARIFICATION);
        assertThat(decision.reasonCode()).isEqualTo("SELECTED_INSTRUMENT_MISMATCH");
        assertThat(decision.clarification()).contains("先切换标的");
    }

    @Test
    void stockModeRejectsPortfolioRouteBecauseWorkspaceIsSingleInstrument() {
        RequestRouter router = router(
                mock(SemanticRouteClassifier.class),
                mock(IntentClassifier.class));

        RouteDecision decision = router.routeStock("分析一下我的持仓组合风险", "600519");

        assertThat(decision.route()).isEqualTo(RequestRoute.NEED_CLARIFICATION);
        assertThat(decision.reasonCode()).isEqualTo("STOCK_WORKSPACE_ROUTE_OUT_OF_SCOPE");
        assertThat(decision.clarification()).contains("单一标的");
    }

    @Test
    void stockModeUsesSelectedInstrumentForDecisionWithoutRepeatingCode() {
        RequestRouter router = router(
                mock(SemanticRouteClassifier.class),
                mock(IntentClassifier.class));

        RouteDecision decision = router.routeStock("现在适合买入吗", "600519");

        assertThat(decision.route()).isEqualTo(RequestRoute.STOCK_DECISION);
        assertThat(decision.symbol()).isEqualTo("600519");
        assertThat(decision.businessRoute()).isEqualTo(BusinessRoute.STOCK_ANALYSIS);
    }

    @Test
    void stockModeRoutesTodayMarketQuestionForSelectedInstrumentToStockSkill() {
        RequestRouter router = router(
                mock(SemanticRouteClassifier.class),
                mock(IntentClassifier.class));

        RouteDecision decision = router.routeStock("今天的行情怎么样", "600519");

        assertThat(decision.route()).isEqualTo(RequestRoute.MARKET_FACT);
        assertThat(decision.symbol()).isEqualTo("600519");
        assertThat(decision.businessRoute()).isEqualTo(BusinessRoute.STOCK_ANALYSIS);
    }

    @Test
    void stockModeRoutesGenericAnalysisOfSelectedInstrumentWithoutTemplateClarification() {
        RequestRouter router = router(
                mock(SemanticRouteClassifier.class),
                mock(IntentClassifier.class));

        RouteDecision decision = router.routeStock("分析现在588200怎么样", "588200");

        assertThat(decision.route()).isEqualTo(RequestRoute.STOCK_DECISION);
        assertThat(decision.needsClarification()).isFalse();
    }

    @Test
    void stockModeAllowsSectorFactWithoutSelectedInstrument() {
        RequestRouter router = router(
                mock(SemanticRouteClassifier.class),
                mock(IntentClassifier.class));

        RouteDecision decision = router.routeStock("今天哪些板块最强", null);

        assertThat(decision.route()).isEqualTo(RequestRoute.SECTOR_FACT);
        assertThat(decision.subjectType()).isEqualTo(RouteSubjectType.MARKET);
        assertThat(decision.modelPolicy()).isEqualTo(ModelPolicy.TEMPLATE_ONLY);
    }

    @Test
    void explicitSectorOverridesSelectedStockContext() {
        RequestRouter router = router(
                mock(SemanticRouteClassifier.class),
                mock(IntentClassifier.class));

        RouteDecision decision = router.routeStock("半导体板块热度怎么样", "600519");

        assertThat(decision.route()).isEqualTo(RequestRoute.SECTOR_FACT);
        assertThat(decision.subjectType()).isEqualTo(RouteSubjectType.SECTOR);
        assertThat(decision.symbol()).isNull();
        assertThat(decision.sectors()).contains("半导体");
    }

    @Test
    void ambiguousStockIntentRequiresClarificationWhenSemanticClassifierUnavailable() {
        IntentClassifier localClassifier = mock(IntentClassifier.class);
        SemanticRouteClassifier semanticClassifier = mock(SemanticRouteClassifier.class);
        when(semanticClassifier.classify(org.mockito.ArgumentMatchers.any()))
                .thenReturn(ClassificationResult.unavailable("TEST_UNAVAILABLE"));
        when(localClassifier.classify("帮我看看600519")).thenReturn(ChatIntent.STOCK_ANALYSIS);
        RequestRouter router = router(semanticClassifier, localClassifier);

        RouteDecision decision = router.route("帮我看看600519");

        assertThat(decision.route()).isEqualTo(RequestRoute.NEED_CLARIFICATION);
        assertThat(decision.modelPolicy()).isEqualTo(ModelPolicy.TEMPLATE_ONLY);
        assertThat(decision.symbol()).isEqualTo("600519");
        assertThat(decision.needsClarification()).isTrue();
    }

    @Test
    void semanticAmbiguityCannotBeOverriddenByLocalClassifier() {
        IntentClassifier localClassifier = mock(IntentClassifier.class);
        SemanticRouteClassifier semanticClassifier = mock(SemanticRouteClassifier.class);
        when(semanticClassifier.classify(org.mockito.ArgumentMatchers.any()))
                .thenReturn(ClassificationResult.ambiguous("请说明要查行情还是做买卖决策。"));
        RequestRouter router = router(semanticClassifier, localClassifier);

        RouteDecision decision = router.route("帮我看看600519");

        assertThat(decision.route()).isEqualTo(RequestRoute.NEED_CLARIFICATION);
        assertThat(decision.clarification()).contains("查行情");
        verify(localClassifier, never()).classify(org.mockito.ArgumentMatchers.anyString());
    }

    @Test
    void semanticCandidateCannotInventSymbol() {
        IntentClassifier localClassifier = mock(IntentClassifier.class);
        SemanticRouteClassifier semanticClassifier = mock(SemanticRouteClassifier.class);
        when(semanticClassifier.classify(org.mockito.ArgumentMatchers.any()))
                .thenReturn(ClassificationResult.classified(new RouteCandidate(
                        RequestRoute.STOCK_DECISION,
                        RouteSubjectType.STOCK,
                        List.of(),
                        SectorType.UNKNOWN,
                        false,
                        0.99,
                        null,
                        RouteSource.DEEPSEEK)));
        RequestRouter router = router(semanticClassifier, localClassifier);

        RouteDecision decision = router.route("这家公司还能买吗");

        assertThat(decision.route()).isEqualTo(RequestRoute.NEED_CLARIFICATION);
        assertThat(decision.reasonCode()).isEqualTo("SINGLE_SYMBOL_REQUIRED");
    }

    private RequestRouter router(SemanticRouteClassifier semanticClassifier,
                                 IntentClassifier localClassifier) {
        SectorEntityResolver sectorResolver = new SectorEntityResolver();
        RouteExecutionPolicyRegistry registry = new RouteExecutionPolicyRegistry();
        return new RequestRouter(
                new DeterministicEntityExtractor(),
                new RuleBasedRouteResolver(sectorResolver),
                semanticClassifier,
                new DeterministicRouteValidator(registry, sectorResolver),
                localClassifier);
    }
}
