package com.stockwise.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.stockwise.agent.AgentRunContext;
import com.stockwise.agent.react.BoundedReactLoop;
import com.stockwise.agent.react.ReactLoopResult;
import com.stockwise.agent.react.ReactObservation;
import com.stockwise.agent.react.ReactTerminationReason;
import com.stockwise.agent.react.ReactToolAction;
import com.stockwise.agent.routing.ExecutionPlan;
import com.stockwise.agent.routing.ExecutionPlanFactory;
import com.stockwise.memory.MemoryRouter;
import com.stockwise.agent.routing.EvidenceBundle;
import com.stockwise.agent.routing.PaidModelGate;
import com.stockwise.agent.routing.PaidModelPermit;
import com.stockwise.agent.routing.RequestRoute;
import com.stockwise.agent.routing.RouteDecision;
import com.stockwise.agent.routing.RouteExecutionPolicyRegistry;
import com.stockwise.agent.routing.RouteSubjectType;
import com.stockwise.agent.routing.SkillObservation;
import com.stockwise.llm.LocalAnswerClient;
import com.stockwise.llm.PaidAnalysisClient;
import com.stockwise.skill.SkillDefinition;
import com.stockwise.tool.StockAnalysisGateway;
import com.stockwise.tool.PortfolioAnalysisInput;
import com.stockwise.tool.StockSkillContractValidator;
import com.stockwise.tool.StockTools;
import com.stockwise.websearch.gateway.WebSearchGateway;
import com.stockwise.websearch.model.SearchTask;
import com.stockwise.websearch.model.WebSearchResponse;
import com.stockwise.websearch.planner.LocalSearchPlanner;
import com.stockwise.websearch.policy.SearchPolicyValidator;
import com.stockwise.websearch.validation.EvidenceValidator;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Flux;

import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 按 Route 显式执行 RAG、WebSearch 和真实 Skill Command，并在唯一门禁后调用付费模型。
 */
@Component
public class ExplicitAnalysisExecutor {

    private static final Pattern SYMBOL_PATTERN = Pattern.compile("(?<!\\d)(\\d{6})(?!\\d)");
    private static final int MAX_MODEL_EVIDENCE_LENGTH = 60_000;

    private final LocalAnswerClient localAnswerClient;
    private final PaidAnalysisClient paidAnalysisClient;
    private final StockAnalysisGateway stockAnalysisGateway;
    private final StockSkillContractValidator contractValidator;
    private final StockTools stockTools;
    private final WebSearchGateway webSearchGateway;
    private final LocalSearchPlanner searchPlanner;
    private final SearchPolicyValidator searchPolicyValidator;
    private final EvidenceValidator evidenceValidator;
    private final RouteExecutionPolicyRegistry policyRegistry;
    private final PaidModelGate paidModelGate;
    private final ExecutionPlanFactory executionPlanFactory;
    private final MarketFactResponder marketFactResponder;
    private final BoundedReactLoop reactLoop;
    private final MemoryRouter memoryRouter;
    private final ObjectMapper objectMapper;

    public ExplicitAnalysisExecutor(LocalAnswerClient localAnswerClient,
                                    PaidAnalysisClient paidAnalysisClient,
                                    StockAnalysisGateway stockAnalysisGateway,
                                    StockSkillContractValidator contractValidator,
                                    StockTools stockTools,
                                    WebSearchGateway webSearchGateway,
                                    LocalSearchPlanner searchPlanner,
                                    SearchPolicyValidator searchPolicyValidator,
                                    EvidenceValidator evidenceValidator,
                                    RouteExecutionPolicyRegistry policyRegistry,
                                    PaidModelGate paidModelGate,
                                    ExecutionPlanFactory executionPlanFactory,
                                    MarketFactResponder marketFactResponder,
                                    BoundedReactLoop reactLoop,
                                    MemoryRouter memoryRouter,
                                    ObjectMapper objectMapper) {
        this.localAnswerClient = localAnswerClient;
        this.paidAnalysisClient = paidAnalysisClient;
        this.stockAnalysisGateway = stockAnalysisGateway;
        this.contractValidator = contractValidator;
        this.stockTools = stockTools;
        this.webSearchGateway = webSearchGateway;
        this.searchPlanner = searchPlanner;
        this.searchPolicyValidator = searchPolicyValidator;
        this.evidenceValidator = evidenceValidator;
        this.policyRegistry = policyRegistry;
        this.paidModelGate = paidModelGate;
        this.executionPlanFactory = executionPlanFactory;
        this.marketFactResponder = marketFactResponder;
        this.reactLoop = reactLoop;
        this.memoryRouter = memoryRouter;
        this.objectMapper = objectMapper;
    }

    /**
     * 执行固定 Route 并返回模型流、模型等级和门禁原因。
     */
    public ExecutionOutput execute(RouteDecision decision,
                                   SkillDefinition skill,
                                   String contextualPrompt,
                                   String rawQuestion,
                                   AgentRunContext runContext) {
        ExecutionPlan plan = executionPlanFactory.create(decision);
        return switch (decision.route()) {
            case GENERAL_CHAT -> local(
                    skill.systemPrompt(), contextualPrompt, "LOCAL", "ROUTE_LOCAL_ONLY",
                    ReactTerminationReason.FINAL_ANSWER);
            case KNOWLEDGE_QA -> knowledge(skill, contextualPrompt, rawQuestion, decision, runContext);
            case EXTERNAL_RESEARCH -> external(skill, contextualPrompt, rawQuestion, decision, runContext);
            case MARKET_FACT -> marketFact(skill, rawQuestion, decision, runContext);
            case STOCK_DECISION -> stockDecision(skill, contextualPrompt, decision, runContext);
            case PORTFOLIO_DECISION -> portfolioDecision(skill, contextualPrompt, decision, runContext);
            case QUANT_DECISION -> quantDecision(
                    skill, contextualPrompt, rawQuestion, decision, runContext, plan);
            case SECTOR_ANALYSIS -> sectorAnalysis(
                    skill, contextualPrompt, decision, runContext, plan);
            case MARKET_CAUSAL_ANALYSIS -> causalAnalysis(
                    skill, contextualPrompt, rawQuestion, decision, runContext, plan);
            case NEED_CLARIFICATION -> new ExecutionOutput(
                    Flux.just(decision.clarification()), "TEMPLATE", "NEED_CLARIFICATION",
                    ReactTerminationReason.ASK_USER, 0, 0, decision.clarification());
        };
    }

    private ExecutionOutput knowledge(SkillDefinition skill,
                                      String prompt,
                                      String question,
                                      RouteDecision decision,
                                      AgentRunContext context) {
        ReactLoopResult loop = reactLoop.execute(
                decision,
                skill,
                context,
                List.of(new ReactToolAction(
                        "searchInvestmentKnowledge",
                        Map.of("question", question),
                        "需要先检索已确认的投资知识，再由本地模型回答",
                        () -> stockTools.searchInvestmentKnowledge(question))));
        if (!loop.completed()) {
            return reactBlocked(loop);
        }
        String evidence = observation(loop, "searchInvestmentKnowledge");
        return local(skill.systemPrompt(), prompt + "\n\n知识库证据：\n" + truncate(evidence),
                "LOCAL", "ROUTE_LOCAL_ONLY", ReactTerminationReason.FINAL_ANSWER, loop);
    }

    private ExecutionOutput external(SkillDefinition skill,
                                     String prompt,
                                     String question,
                                     RouteDecision decision,
                                     AgentRunContext context) {
        SearchPlan plan = searchPlan(decision, question);
        ReactLoopResult loop = reactLoop.execute(
                decision, skill, context, List.of(plan.action()));
        if (!loop.completed()) {
            return reactBlocked(loop);
        }
        SearchExecution search = searchResult(decision, observation(loop, "webSearch"));
        if (!search.evidence().sufficient()) {
            return new ExecutionOutput(Flux.just("外部搜索没有返回足够的可靠资料，当前无法给出确定结论。"),
                    "TEMPLATE", "EXTERNAL_EVIDENCE_INSUFFICIENT",
                    ReactTerminationReason.EVIDENCE_INSUFFICIENT,
                    loop.rounds(), loop.toolCalls(), "外部证据未达到 Route 最低要求");
        }
        return local(skill.systemPrompt(),
                prompt + "\n\n外部资料（只能依据这些资料总结，并标注来源URL）：\n" + truncate(search.json()),
                "LOCAL", "ROUTE_LOCAL_ONLY", ReactTerminationReason.FINAL_ANSWER, loop);
    }

    private ExecutionOutput marketFact(SkillDefinition skill,
                                       String question,
                                       RouteDecision decision,
                                       AgentRunContext context) {
        ReactLoopResult loop = reactLoop.execute(
                decision, skill, context, List.of(stockAction(decision)));
        if (!loop.completed()) {
            return reactBlocked(loop);
        }
        String stockJson = observation(loop, "stock");
        JsonNode validated = contractValidator.validate(stockJson, "stock");
        return new ExecutionOutput(
                Flux.just(marketFactResponder.respond(decision.symbol(), question, validated)),
                "TEMPLATE",
                "MARKET_FACT_TEMPLATE",
                ReactTerminationReason.FINAL_ANSWER,
                loop.rounds(), loop.toolCalls(), "行情事实模板回答");
    }

    private ExecutionOutput stockDecision(SkillDefinition skill,
                                          String prompt,
                                          RouteDecision decision,
                                          AgentRunContext context) {
        ReactLoopResult loop = reactLoop.execute(
                decision, skill, context, List.of(stockAction(decision)));
        if (!loop.completed()) {
            return reactBlocked(loop);
        }
        String stockJson = observation(loop, "stock");
        JsonNode validated = contractValidator.validate(stockJson, "stock");
        boolean fresh = contractValidator.policy(validated).directionalSignalAllowed();
        PaidModelPermit permit = gate(
                decision,
                fresh,
                stockSubjectMatches(validated, decision.primarySymbol()),
                EvidenceBundle.notRequired());
        if (!permit.allowed()) {
            return blocked(permit, loop);
        }
        return paid(skill.systemPrompt(), prompt + "\n\n已校验行情数据：\n" + truncate(stockJson), permit, loop);
    }

    private ExecutionOutput portfolioDecision(SkillDefinition skill,
                                              String prompt,
                                              RouteDecision decision,
                                              AgentRunContext context) {
        requireCommand(decision, "portfolio");
        PortfolioAnalysisInput portfolio;
        try {
            portfolio = memoryRouter.loadRequiredPortfolio(context.userId());
        } catch (PortfolioDataMissingException e) {
            return new ExecutionOutput(
                    Flux.just(e.getMessage()),
                    "TEMPLATE",
                    "PORTFOLIO_DATA_REQUIRED",
                    ReactTerminationReason.ASK_USER,
                    0,
                    0,
                    e.getMessage());
        }
        ReactLoopResult loop = reactLoop.execute(
                decision,
                skill,
                context,
                List.of(new ReactToolAction(
                        "portfolio",
                        Map.of("positionCount", portfolio.positions().size()),
                        "需要先加载并核验真实持仓，再判断组合风险",
                        () -> stockAnalysisGateway.portfolio(portfolio))));
        if (!loop.completed()) {
            return reactBlocked(loop);
        }
        String result = observation(loop, "portfolio");
        JsonNode validated = contractValidator.validate(result, "portfolio");
        PaidModelPermit permit = gate(decision, hasVerifiedDataQuality(validated), EvidenceBundle.notRequired());
        if (!permit.allowed()) {
            return blocked(permit, loop);
        }
        return paid(skill.systemPrompt(), prompt + "\n\n已校验持仓数据：\n" + truncate(result), permit, loop);
    }

    private ExecutionOutput quantDecision(SkillDefinition skill,
                                          String prompt,
                                          String question,
                                          RouteDecision decision,
                                          AgentRunContext context,
                                          ExecutionPlan plan) {
        requirePlannedCommand(decision, plan, "quant");
        List<String> codes = decision.symbols().isEmpty()
                ? extractSymbols(question)
                : decision.symbols();
        if (codes.size() < 2) {
            return new ExecutionOutput(Flux.just("请至少提供两个需要比较的6位ETF代码。"),
                    "TEMPLATE", "MISSING_QUANT_UNIVERSE",
                    ReactTerminationReason.ASK_USER, 0, 0, "缺少量化比较标的池");
        }
        ReactToolAction action = new ReactToolAction(
                "quant",
                Map.of("codes", codes, "benchmark", codes.get(0)),
                "需要先计算标的池的确定性量化结果，再形成比较结论",
                () -> stockAnalysisGateway.quant(codes, codes.get(0)));
        ReactLoopResult loop = reactLoop.execute(decision, skill, context, List.of(action));
        if (!loop.completed()) {
            return reactBlocked(loop);
        }
        String result = observation(loop, "quant");
        JsonNode validated = contractValidator.validate(result, "quant");
        PaidModelPermit permit = gate(
                decision,
                hasVerifiedDataQuality(validated),
                quantSubjectsMatch(validated, codes),
                EvidenceBundle.notRequired());
        if (!permit.allowed()) {
            return blocked(permit, loop);
        }
        return paid(skill.systemPrompt(), prompt + "\n\n已校验量化数据：\n" + truncate(result), permit, loop);
    }

    private ExecutionOutput sectorAnalysis(SkillDefinition skill,
                                           String prompt,
                                           RouteDecision decision,
                                           AgentRunContext context,
                                           ExecutionPlan plan) {
        requirePlannedCommand(decision, plan, "sector");
        ReactLoopResult loop = reactLoop.execute(
                decision, skill, context, List.of(sectorAction(decision)));
        if (!loop.completed()) {
            return reactBlocked(loop);
        }
        String result = observation(loop, "sector");
        JsonNode validated = contractValidator.validate(result, "sector");
        PaidModelPermit permit = gate(
                decision,
                hasVerifiedDataQuality(validated),
                sectorSubjectsMatch(validated, decision),
                EvidenceBundle.notRequired());
        if (!permit.allowed()) {
            return blocked(permit, loop);
        }
        return paid(skill.systemPrompt(), prompt + "\n\n已校验板块数据：\n" + truncate(result), permit, loop);
    }

    private ExecutionOutput causalAnalysis(SkillDefinition skill,
                                           String prompt,
                                           String question,
                                           RouteDecision decision,
                                           AgentRunContext context,
                                           ExecutionPlan plan) {
        SearchPlan searchPlan = searchPlan(decision, question);
        ReactToolAction marketAction;
        if (decision.subjectType() == RouteSubjectType.STOCK) {
            requirePlannedCommand(decision, plan, "stock");
            marketAction = stockAction(decision);
        } else if (decision.subjectType() == RouteSubjectType.SECTOR
                || decision.subjectType() == RouteSubjectType.MARKET) {
            requirePlannedCommand(decision, plan, "sector");
            marketAction = sectorAction(decision);
        } else {
            return new ExecutionOutput(
                    Flux.just("请说明该事件影响的具体股票、板块或整体市场。"),
                    "TEMPLATE",
                    "CAUSAL_SUBJECT_REQUIRED",
                    ReactTerminationReason.ASK_USER,
                    0,
                    0,
                    "因果分析缺少可执行主体");
        }
        ReactLoopResult loop = reactLoop.execute(
                decision,
                skill,
                context,
                List.of(marketAction, searchPlan.action()));
        if (!loop.completed()) {
            return reactBlocked(loop);
        }
        String command = decision.subjectType() == RouteSubjectType.STOCK ? "stock" : "sector";
        String marketJson = observation(loop, command);
        JsonNode validated = contractValidator.validate(marketJson, command);
        boolean fresh = "stock".equals(command)
                ? contractValidator.policy(validated).directionalSignalAllowed()
                : hasVerifiedDataQuality(validated);
        boolean subjectMatches = "stock".equals(command)
                ? stockSubjectMatches(validated, decision.primarySymbol())
                : sectorSubjectsMatch(validated, decision);
        SearchExecution search = searchResult(decision, observation(loop, "webSearch"));
        PaidModelPermit permit = gate(decision, fresh, subjectMatches, search.evidence());
        if (!permit.allowed()) {
            return blocked(permit, loop);
        }
        String modelPrompt = prompt
                + "\n\n已校验市场数据：\n" + truncate(marketJson)
                + "\n\n已校验外部资料：\n" + truncate(search.json());
        return paid(skill.systemPrompt(), modelPrompt, permit, loop);
    }

    private SearchPlan searchPlan(RouteDecision decision, String question) {
        List<SearchTask> tasks = searchPolicyValidator.validate(searchPlanner.plan(decision, question));
        ReactToolAction action = new ReactToolAction(
                "webSearch",
                Map.of("taskCount", tasks.size(), "purposes",
                        tasks.stream().map(task -> task.purpose().name()).toList()),
                "需要获取固定契约的外部资料，补足当前 Route 要求的时效证据",
                () -> json(webSearchGateway.search(tasks)));
        return new SearchPlan(action);
    }

    private SearchExecution searchResult(RouteDecision decision, String responseJson) {
        try {
            WebSearchResponse response = objectMapper.readValue(responseJson, WebSearchResponse.class);
            EvidenceBundle evidence = evidenceValidator.validate(decision.route(), response.results());
            return new SearchExecution(responseJson, evidence);
        } catch (Exception e) {
            throw new IllegalStateException("标准化搜索结果解析失败", e);
        }
    }

    private ReactToolAction stockAction(RouteDecision decision) {
        requireCommand(decision, "stock");
        String symbol = decision.primarySymbol();
        if (symbol == null) {
            throw new IllegalStateException("单标的 Route 缺少唯一代码");
        }
        return new ReactToolAction(
                "stock",
                Map.of("symbol", symbol, "assetType", "auto"),
                "必须先获取并校验标的行情，方向判断不能依赖用户口述",
                () -> {
                    String raw = stockAnalysisGateway.stock(symbol, "auto");
                    return contractValidator.validateAndAnnotate(raw, "stock");
                });
    }

    private ReactToolAction sectorAction(RouteDecision decision) {
        requireCommand(decision, "sector");
        if (decision.sectorType() == null || decision.sectorType().commandValue().isBlank()) {
            throw new IllegalStateException("板块 Route 缺少受限行业或概念类型");
        }
        int limit = decision.sectors().isEmpty() ? 20 : 100;
        String type = decision.sectorType().commandValue();
        return new ReactToolAction(
                "sector",
                Map.of("type", type, "limit", limit, "sectors", decision.sectors()),
                "必须先获取并校验板块排名、趋势和资金流数据，再形成方向判断",
                () -> stockAnalysisGateway.sector(type, limit));
    }

    private PaidModelPermit gate(RouteDecision decision,
                                 boolean freshnessValidated,
                                 EvidenceBundle evidence) {
        return gate(decision, freshnessValidated, true, evidence);
    }

    private PaidModelPermit gate(RouteDecision decision,
                                 boolean freshnessValidated,
                                 boolean subjectMatches,
                                 EvidenceBundle evidence) {
        SkillObservation observation = new SkillObservation(
                true, true, true, subjectMatches, freshnessValidated);
        return paidModelGate.evaluate(decision, observation, evidence);
    }

    private void requireCommand(RouteDecision decision, String command) {
        if (!policyRegistry.allowsCommand(decision.route(), command)) {
            throw new IllegalStateException("Route " + decision.route() + " 不允许执行命令 " + command);
        }
    }

    private void requirePlannedCommand(RouteDecision decision,
                                       ExecutionPlan plan,
                                       String command) {
        requireCommand(decision, command);
        if (plan == null || !plan.allows(command)) {
            throw new IllegalStateException(
                    "Route " + decision.route() + " 的本轮执行计划不允许命令 " + command);
        }
    }

    private ExecutionOutput local(String systemPrompt,
                                  String prompt,
                                  String tier,
                                  String reason,
                                  ReactTerminationReason terminationReason) {
        return new ExecutionOutput(
                localAnswerClient.streamChat(systemPrompt, prompt),
                tier,
                reason,
                terminationReason,
                0,
                0,
                "当前 Route 不需要工具 Action");
    }

    private ExecutionOutput local(String systemPrompt,
                                  String prompt,
                                  String tier,
                                  String reason,
                                  ReactTerminationReason terminationReason,
                                  ReactLoopResult loop) {
        return new ExecutionOutput(
                localAnswerClient.streamChat(systemPrompt, prompt),
                tier,
                reason,
                terminationReason,
                loop.rounds(),
                loop.toolCalls(),
                loop.detail());
    }

    private ExecutionOutput paid(String systemPrompt,
                                 String prompt,
                                 PaidModelPermit permit,
                                 ReactLoopResult loop) {
        return new ExecutionOutput(
                paidAnalysisClient.streamChat(permit, systemPrompt, prompt),
                "PAID",
                permit.reasonCode(),
                ReactTerminationReason.FINAL_ANSWER,
                loop.rounds(),
                loop.toolCalls(),
                loop.detail());
    }

    private ExecutionOutput blocked(PaidModelPermit permit, ReactLoopResult loop) {
        return new ExecutionOutput(Flux.just(
                "确定性数据或外部证据未通过分析门禁，本次不调用深度分析模型。原因：" + permit.reasonCode()),
                "TEMPLATE",
                permit.reasonCode(),
                ReactTerminationReason.MODEL_GATE_BLOCKED,
                loop.rounds(),
                loop.toolCalls(),
                permit.reasonCode());
    }

    private ExecutionOutput reactBlocked(ReactLoopResult loop) {
        return new ExecutionOutput(
                Flux.just("本次分析已由有界 ReAct 控制器停止。原因："
                        + loop.terminationReason().name() + "；" + loop.detail()),
                "TEMPLATE",
                loop.terminationReason().name(),
                loop.terminationReason(),
                loop.rounds(),
                loop.toolCalls(),
                loop.detail());
    }

    private String observation(ReactLoopResult loop, String toolName) {
        return loop.observation(toolName)
                .map(ReactObservation::output)
                .orElseThrow(() -> new IllegalStateException("ReAct 缺少工具 Observation: " + toolName));
    }

    private boolean hasVerifiedDataQuality(JsonNode root) {
        JsonNode quality = root.path("dataQuality");
        String asOf = root.path("asOf").asText(quality.path("asOf").asText(""));
        return !asOf.isBlank() && quality.path("allowsDirectionalSignal").asBoolean(false);
    }

    private boolean stockSubjectMatches(JsonNode root, String symbol) {
        if (symbol == null || symbol.isBlank()) {
            return false;
        }
        String actual = root.path("data").path("code").asText(
                root.path("data").path("symbol").asText(""));
        return symbol.equals(actual);
    }

    private boolean quantSubjectsMatch(JsonNode root, List<String> codes) {
        if (codes == null || codes.size() < 2) {
            return false;
        }
        String json = root.toString();
        return codes.stream().allMatch(json::contains);
    }

    private boolean sectorSubjectsMatch(JsonNode root, RouteDecision decision) {
        String expectedType = decision.sectorType() == null
                ? ""
                : decision.sectorType().commandValue();
        String actualType = root.path("request").path("type").asText("");
        if (!actualType.isBlank() && !expectedType.equals(actualType)) {
            return false;
        }
        if (decision.sectors().isEmpty()) {
            return true;
        }
        String json = root.toString();
        return decision.sectors().stream().allMatch(json::contains);
    }

    private List<String> extractSymbols(String question) {
        Matcher matcher = SYMBOL_PATTERN.matcher(question == null ? "" : question);
        java.util.LinkedHashSet<String> result = new java.util.LinkedHashSet<>();
        while (matcher.find()) {
            result.add(matcher.group(1));
        }
        return result.stream().toList();
    }

    private String json(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception e) {
            throw new IllegalStateException("审计数据序列化失败", e);
        }
    }

    private String truncate(String value) {
        if (value == null || value.length() <= MAX_MODEL_EVIDENCE_LENGTH) {
            return value == null ? "" : value;
        }
        return value.substring(0, MAX_MODEL_EVIDENCE_LENGTH) + "…";
    }

    /**
     * 表示一次显式执行的模型输出和审计元数据。
     */
    public record ExecutionOutput(
            Flux<String> content,
            String modelTier,
            String gateReason,
            ReactTerminationReason reactTerminationReason,
            int reactRounds,
            int reactToolCalls,
            String reactDetail
    ) {
    }

    private record SearchExecution(String json, EvidenceBundle evidence) {
    }

    private record SearchPlan(ReactToolAction action) {
    }
}
