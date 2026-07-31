package com.stockwise.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.stockwise.agent.AgentRunContext;
import com.stockwise.agent.react.BoundedReactLoop;
import com.stockwise.agent.routing.ModelPolicy;
import com.stockwise.agent.routing.ExecutionPlanFactory;
import com.stockwise.agent.routing.PaidModelGate;
import com.stockwise.agent.routing.RequestRoute;
import com.stockwise.agent.routing.RouteDecision;
import com.stockwise.agent.routing.RouteExecutionPolicyRegistry;
import com.stockwise.agent.routing.RouteSource;
import com.stockwise.agent.routing.RouteSubjectType;
import com.stockwise.agent.routing.SectorType;
import com.stockwise.llm.ChatIntent;
import com.stockwise.llm.LocalAnswerClient;
import com.stockwise.llm.PaidAnalysisClient;
import com.stockwise.memory.MemoryRouter;
import com.stockwise.skill.SkillDefinition;
import com.stockwise.skill.SkillRegistry;
import com.stockwise.tool.StockAnalysisGateway;
import com.stockwise.tool.PortfolioAnalysisInput;
import com.stockwise.tool.StockSkillContractValidator;
import com.stockwise.tool.StockTools;
import com.stockwise.websearch.gateway.WebSearchGateway;
import com.stockwise.websearch.model.SearchPurpose;
import com.stockwise.websearch.model.SearchResult;
import com.stockwise.websearch.model.SearchTask;
import com.stockwise.websearch.model.WebSearchResponse;
import com.stockwise.websearch.planner.LocalSearchPlanner;
import com.stockwise.websearch.policy.SearchPolicyValidator;
import com.stockwise.websearch.validation.EvidenceValidator;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import reactor.core.publisher.Flux;

import java.time.Instant;
import java.time.LocalDate;
import java.math.BigDecimal;
import java.util.List;
import java.util.UUID;
import java.util.function.Supplier;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 验证显式执行器的模型隔离，确保非付费 Route 无法旁路调用 DeepSeek。
 */
class ExplicitAnalysisExecutorTest {

    private LocalAnswerClient localAnswerClient;
    private PaidAnalysisClient paidAnalysisClient;
    private StockAnalysisGateway stockAnalysisGateway;
    private StockSkillContractValidator contractValidator;
    private StockTools stockTools;
    private WebSearchGateway webSearchGateway;
    private LocalSearchPlanner searchPlanner;
    private SearchPolicyValidator searchPolicyValidator;
    private MarketFactResponder marketFactResponder;
    private AgentRunService agentRunService;
    private MemoryRouter memoryRouter;
    private BoundedReactLoop reactLoop;
    private ExplicitAnalysisExecutor executor;
    private final SkillRegistry skillRegistry = new SkillRegistry();
    private final ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();

    @BeforeEach
    void setUp() {
        localAnswerClient = mock(LocalAnswerClient.class);
        paidAnalysisClient = mock(PaidAnalysisClient.class);
        stockAnalysisGateway = mock(StockAnalysisGateway.class);
        contractValidator = mock(StockSkillContractValidator.class);
        stockTools = mock(StockTools.class);
        webSearchGateway = mock(WebSearchGateway.class);
        searchPlanner = mock(LocalSearchPlanner.class);
        searchPolicyValidator = mock(SearchPolicyValidator.class);
        marketFactResponder = mock(MarketFactResponder.class);
        agentRunService = mock(AgentRunService.class);
        memoryRouter = mock(MemoryRouter.class);

        RouteExecutionPolicyRegistry policyRegistry = new RouteExecutionPolicyRegistry();
        reactLoop = new BoundedReactLoop(
                policyRegistry, agentRunService, objectMapper,
                5, 180_000, 60_000, 1, 8_000);
        executor = new ExplicitAnalysisExecutor(
                localAnswerClient,
                paidAnalysisClient,
                stockAnalysisGateway,
                contractValidator,
                stockTools,
                webSearchGateway,
                searchPlanner,
                searchPolicyValidator,
                new EvidenceValidator(),
                policyRegistry,
                new PaidModelGate(policyRegistry),
                new ExecutionPlanFactory(),
                marketFactResponder,
                reactLoop,
                memoryRouter,
                objectMapper);

        when(localAnswerClient.streamChat(anyString(), anyString())).thenReturn(Flux.just("本地回答"));
        when(agentRunService.executeTool(any(), anyString(), anyString(), any()))
                .thenAnswer(invocation -> {
                    Supplier<String> action = invocation.getArgument(3);
                    return action.get();
                });
    }

    @AfterEach
    void tearDown() {
        reactLoop.close();
    }

    @Test
    void nonPaidRoutesNeverInvokeDeepSeek() {
        // 1. 普通问答只允许本地模型
        ExecutionResult general = execute(decision(
                RequestRoute.GENERAL_CHAT, ChatIntent.GENERAL_CHAT, ModelPolicy.LOCAL_ONLY, null));
        assertThat(general.modelTier()).isEqualTo("LOCAL");

        // 2. 知识问答只允许知识库和本地模型
        when(stockTools.searchInvestmentKnowledge(anyString())).thenReturn("{\"items\":[]}");
        ExecutionResult knowledge = execute(decision(
                RequestRoute.KNOWLEDGE_QA, ChatIntent.INVESTMENT_QA, ModelPolicy.LOCAL_ONLY, null));
        assertThat(knowledge.modelTier()).isEqualTo("LOCAL");

        // 3. 外部研究只消费固定搜索结果并由本地模型总结
        SearchTask task = new SearchTask(
                "news-1", SearchPurpose.NEWS_CATALYST, "贵州茅台 最新公告",
                "600519", 7, List.of(), 3);
        when(searchPlanner.plan(any(), anyString())).thenReturn(List.of(task));
        when(searchPolicyValidator.validate(any())).thenReturn(List.of(task));
        when(webSearchGateway.search(any())).thenReturn(new WebSearchResponse(
                "request-1",
                "searxng",
                List.of(result("result-1", "news-1", "example.com")),
                List.of()));
        ExecutionResult external = execute(decision(
                RequestRoute.EXTERNAL_RESEARCH, ChatIntent.INVESTMENT_QA, ModelPolicy.LOCAL_ONLY, "600519"));
        assertThat(external.modelTier()).isEqualTo("LOCAL");

        // 4. 行情事实查询只使用固定模板
        String stockJson = "{\"schemaVersion\":\"1.1\",\"command\":\"stock\",\"data\":{}}";
        when(stockAnalysisGateway.stock("600519", "auto")).thenReturn(stockJson);
        when(contractValidator.validateAndAnnotate(stockJson, "stock")).thenReturn(stockJson);
        when(contractValidator.validate(stockJson, "stock")).thenReturn(
                objectMapper.createObjectNode().set(
                        "data",
                        objectMapper.createObjectNode().put("code", "600519")));
        when(marketFactResponder.respond(anyString(), anyString(), any())).thenReturn("现价：测试值");
        ExecutionResult marketFact = execute(decision(
                RequestRoute.MARKET_FACT, ChatIntent.STOCK_ANALYSIS, ModelPolicy.TEMPLATE_ONLY, "600519"));
        assertThat(marketFact.modelTier()).isEqualTo("TEMPLATE");

        verify(paidAnalysisClient, never()).streamChat(any(), anyString(), anyString());
    }

    @Test
    void staleSkillObservationBlocksPaidModel() {
        String stockJson = "{\"schemaVersion\":\"1.1\",\"command\":\"stock\",\"data\":{}}";
        when(stockAnalysisGateway.stock("600519", "auto")).thenReturn(stockJson);
        when(contractValidator.validateAndAnnotate(stockJson, "stock")).thenReturn(stockJson);
        when(contractValidator.validate(stockJson, "stock")).thenReturn(
                objectMapper.createObjectNode().set(
                        "data",
                        objectMapper.createObjectNode().put("code", "600519")));
        when(contractValidator.policy(any())).thenReturn(new StockSkillContractValidator.StockConsumerPolicy(
                false, false, false, "wait", "", List.of("数据过期")));

        ExecutionResult result = execute(decision(
                RequestRoute.STOCK_DECISION,
                ChatIntent.STOCK_ANALYSIS,
                ModelPolicy.PAID_AFTER_VALIDATED_SKILL,
                "600519"));

        assertThat(result.modelTier()).isEqualTo("TEMPLATE");
        assertThat(result.content()).contains("SKILL_DATA_STALE");
        verify(paidAnalysisClient, never()).streamChat(any(), anyString(), anyString());
    }

    @Test
    void portfolioRouteShouldAskForRealDataInsteadOfUsingExamplePortfolio() {
        when(memoryRouter.loadRequiredPortfolio(7L))
                .thenThrow(new PortfolioDataMissingException("请先录入至少一条有效持仓"));
        RouteDecision decision = decision(
                RequestRoute.PORTFOLIO_DECISION,
                ChatIntent.PORTFOLIO_ANALYSIS,
                ModelPolicy.PAID_AFTER_VALIDATED_SKILL,
                null);
        SkillDefinition skill = skillRegistry.get(decision.compatibleIntent());

        ExplicitAnalysisExecutor.ExecutionOutput output = executor.execute(
                decision,
                skill,
                "带上下文的问题",
                "分析我的组合",
                new AgentRunContext(UUID.randomUUID(), 7L, 5));

        assertThat(output.modelTier()).isEqualTo("TEMPLATE");
        assertThat(output.gateReason()).isEqualTo("PORTFOLIO_DATA_REQUIRED");
        assertThat(output.reactTerminationReason().name()).isEqualTo("ASK_USER");
        assertThat(output.content().collectList().block()).containsExactly("请先录入至少一条有效持仓");
        verify(memoryRouter).loadRequiredPortfolio(7L);
        verify(stockAnalysisGateway, never()).portfolio(any());
        verify(paidAnalysisClient, never()).streamChat(any(), anyString(), anyString());
    }

    @Test
    void portfolioRouteShouldBlockPaidModelWhenAggregateQualityIsLimited() throws Exception {
        PortfolioAnalysisInput portfolio = new PortfolioAnalysisInput(
                new BigDecimal("5000"),
                new BigDecimal("12000"),
                new BigDecimal("0.20"),
                List.of(new PortfolioAnalysisInput.Position(
                        "588200", "科创芯片ETF", "etf",
                        new BigDecimal("1.20"), new BigDecimal("1000"),
                        LocalDate.of(2026, 1, 2), new BigDecimal("0.30"),
                        "半导体", "进攻")));
        String json = """
                {
                  "schemaVersion":"1.1",
                  "command":"portfolio",
                  "timezone":"Asia/Shanghai",
                  "asOf":"2026-07-29 10:00:00",
                  "dataQuality":{
                    "status":"limited",
                    "asOf":"2026-07-29 10:00:00",
                    "allowsDirectionalSignal":false
                  },
                  "data":{"holdings":[]},
                  "sources":{}
                }
                """;
        when(memoryRouter.loadRequiredPortfolio(7L)).thenReturn(portfolio);
        when(stockAnalysisGateway.portfolio(portfolio)).thenReturn(json);
        when(contractValidator.validate(json, "portfolio")).thenReturn(objectMapper.readTree(json));
        RouteDecision decision = decision(
                RequestRoute.PORTFOLIO_DECISION,
                ChatIntent.PORTFOLIO_ANALYSIS,
                ModelPolicy.PAID_AFTER_VALIDATED_SKILL,
                null);
        SkillDefinition skill = skillRegistry.get(decision.compatibleIntent());

        ExplicitAnalysisExecutor.ExecutionOutput output = executor.execute(
                decision,
                skill,
                "带上下文的问题",
                "分析我的组合",
                new AgentRunContext(UUID.randomUUID(), 7L, 5));

        assertThat(output.modelTier()).isEqualTo("TEMPLATE");
        verify(stockAnalysisGateway).portfolio(portfolio);
        verify(paidAnalysisClient, never()).streamChat(any(), anyString(), anyString());
    }

    @Test
    void sectorRouteUsesConceptDataAndPaidGate() throws Exception {
        String json = """
                {
                  "schemaVersion":"1.1",
                  "command":"sector",
                  "timezone":"Asia/Shanghai",
                  "asOf":"2026-07-30 10:00:00",
                  "request":{"type":"concept","limit":100},
                  "dataQuality":{
                    "status":"verified",
                    "asOf":"2026-07-30 10:00:00",
                    "allowsDirectionalSignal":true
                  },
                  "data":{"rankings":[{"name":"新能源车"}]},
                  "sources":{}
                }
                """;
        when(stockAnalysisGateway.sector("concept", 100)).thenReturn(json);
        when(contractValidator.validate(json, "sector")).thenReturn(objectMapper.readTree(json));
        when(paidAnalysisClient.streamChat(any(), anyString(), anyString()))
                .thenReturn(Flux.just("板块分析"));
        RouteDecision decision = new RouteDecision(
                RequestRoute.SECTOR_ANALYSIS,
                ChatIntent.PORTFOLIO_ANALYSIS,
                ModelPolicy.PAID_AFTER_VALIDATED_SKILL,
                RouteSubjectType.SECTOR,
                List.of(),
                List.of("新能源车"),
                SectorType.CONCEPT,
                "TEST_SECTOR",
                RouteSource.REGEX,
                1.0,
                true,
                false,
                false,
                null);

        ExplicitAnalysisExecutor.ExecutionOutput output = executor.execute(
                decision,
                skillRegistry.get(decision),
                "带上下文的问题",
                "新能源车是不是到顶了",
                new AgentRunContext(UUID.randomUUID()));

        assertThat(output.modelTier()).isEqualTo("PAID");
        assertThat(output.content().collectList().block()).containsExactly("板块分析");
        verify(stockAnalysisGateway).sector("concept", 100);
        verify(paidAnalysisClient).streamChat(any(), anyString(), anyString());
    }

    private ExecutionResult execute(RouteDecision decision) {
        SkillDefinition skill = skillRegistry.get(decision.compatibleIntent());
        ExplicitAnalysisExecutor.ExecutionOutput output = executor.execute(
                decision,
                skill,
                "带上下文的问题",
                "原始问题",
                new AgentRunContext(UUID.randomUUID()));
        return new ExecutionResult(output.content().collectList().block(), output.modelTier());
    }

    private RouteDecision decision(RequestRoute route,
                                   ChatIntent intent,
                                   ModelPolicy modelPolicy,
                                   String symbol) {
        return new RouteDecision(
                route,
                intent,
                modelPolicy,
                symbol,
                "TEST",
                1.0,
                route != RequestRoute.GENERAL_CHAT && route != RequestRoute.KNOWLEDGE_QA,
                route == RequestRoute.EXTERNAL_RESEARCH,
                false,
                null);
    }

    private SearchResult result(String resultId, String taskId, String domain) {
        return new SearchResult(
                resultId,
                taskId,
                SearchPurpose.NEWS_CATALYST,
                "标题",
                "https://" + domain + "/article",
                domain,
                "摘要",
                "MEDIA",
                "searxng",
                Instant.now(),
                Instant.now(),
                0.9);
    }

    private record ExecutionResult(List<String> chunks, String modelTier) {
        private String content() {
            return String.join("", chunks);
        }
    }
}
