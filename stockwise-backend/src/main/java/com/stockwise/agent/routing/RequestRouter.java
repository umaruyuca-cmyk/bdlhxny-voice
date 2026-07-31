package com.stockwise.agent.routing;

import com.stockwise.llm.ChatIntent;
import com.stockwise.llm.IntentClassifier;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Optional;
import java.util.regex.Pattern;

/**
 * 合并确定性规则、语义候选分类和 Java 校验，并始终输出受限 RouteDecision。
 */
@Component
public class RequestRouter {

    private static final Pattern GENERAL_TOOL_PATTERN = Pattern.compile(
            "(搜索|搜一下|查一下|查询|核验|验证|来源|链接|最新|近期|今天|昨日|刚刚|"
                    + "最近|实时|当前|截至|新闻|公告|政策|法规|发布|进展|发生了什么)",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern VAGUE_MARKET_ANALYSIS_PATTERN = Pattern.compile(
            "(板块|行业|大盘|市场|指数).*(分析|情况|怎么样|如何|表现|趋势|复盘)|"
                    + "(分析|看看|复盘).*(板块|行业|大盘|市场|指数)");
    private static final Pattern MARKET_ANALYSIS_SCOPE_PATTERN = Pattern.compile(
            "(昨日|昨天|今日|今天|本周|本月|近期|最近|近\\s*\\d+\\s*(日|天|周|月)|"
                    + "资金|涨跌|成交|技术|估值|消息|新闻|政策|原因|影响|对比|排名|强弱)");

    private final DeterministicEntityExtractor entityExtractor;
    private final RuleBasedRouteResolver ruleResolver;
    private final SemanticRouteClassifier semanticClassifier;
    private final DeterministicRouteValidator routeValidator;
    private final IntentClassifier intentClassifier;

    public RequestRouter(DeterministicEntityExtractor entityExtractor,
                         RuleBasedRouteResolver ruleResolver,
                         SemanticRouteClassifier semanticClassifier,
                         DeterministicRouteValidator routeValidator,
                         IntentClassifier intentClassifier) {
        this.entityExtractor = entityExtractor;
        this.ruleResolver = ruleResolver;
        this.semanticClassifier = semanticClassifier;
        this.routeValidator = routeValidator;
        this.intentClassifier = intentClassifier;
    }

    /**
     * 在没有前端当前标的时执行三层路由，持仓可用性仍由执行层做最终校验。
     */
    public RouteDecision route(String question) {
        return route(question, null, true);
    }

    /**
     * 使用结构化当前标的补足省略代码的问题，持仓可用性仍由执行层做最终校验。
     */
    public RouteDecision route(String question, String contextSymbol) {
        return route(question, contextSymbol, true);
    }

    /**
     * 使用最小上下文完成规则、语义候选和确定性校验，不让分类器直接授权执行。
     */
    public RouteDecision route(String question, String contextSymbol, boolean portfolioAvailable) {
        RoutingContext context = entityExtractor.extract(question, contextSymbol, portfolioAvailable);

        // 1. Regex 只返回能够唯一决定 Route 的候选，命中后仍执行统一校验。
        Optional<RouteCandidate> regexCandidate = ruleResolver.resolve(context);
        if (regexCandidate.isPresent()) {
            return routeValidator.validate(context, regexCandidate.get());
        }

        // 2. DeepSeek 只生成候选；语义本身不明确时直接追问，不能被低级分类器覆盖。
        ClassificationResult semantic = semanticClassifier.classify(context);
        if (semantic != null && semantic.status() == ClassificationStatus.CLASSIFIED) {
            return routeValidator.validate(context, semantic.candidate());
        }
        if (semantic != null && semantic.status() == ClassificationStatus.AMBIGUOUS) {
            return routeValidator.clarification(
                    context,
                    "SEMANTIC_AMBIGUOUS",
                    semantic.detail() == null ? "请补充你想分析的具体目标。" : semantic.detail());
        }

        // 3. 只有外部分类器不可用时才进入本地保守兜底，结果仍需统一校验。
        ChatIntent intent = intentClassifier.classify(context.question());
        return routeValidator.validate(context, localFallback(intent));
    }

    /**
     * 普通问答只允许直接回答或受限 WebSearch，不允许进入股票、持仓和量化 Skill。
     */
    public RouteDecision routeGeneral(String question) {
        RoutingContext context = entityExtractor.extract(question, null, false);
        boolean marketAnalysis = VAGUE_MARKET_ANALYSIS_PATTERN.matcher(context.question()).find();
        if (marketAnalysis && !MARKET_ANALYSIS_SCOPE_PATTERN.matcher(context.question()).find()) {
            return routeValidator.clarification(
                    context,
                    "GENERAL_RESEARCH_SCOPE_REQUIRED",
                    "你更想从哪个角度分析？选择一个方向后，我会检索实际数据并给出精简结论。");
        }
        RequestRoute route = GENERAL_TOOL_PATTERN.matcher(context.question()).find()
                || marketAnalysis
                ? RequestRoute.EXTERNAL_RESEARCH
                : RequestRoute.GENERAL_CHAT;
        return routeValidator.validate(context, candidate(route, RouteSubjectType.NONE, null));
    }

    /**
     * Stock Agent 以用户已选标的为唯一可信主体，同时允许闲聊和投资知识走非分析 Route。
     */
    public RouteDecision routeStock(String question, String selectedSymbol) {
        RoutingContext context = entityExtractor.extract(question, selectedSymbol, false);
        if (context.contextSymbol() == null) {
            return routeValidator.clarification(
                    context,
                    "SELECTED_INSTRUMENT_REQUIRED",
                    "请先选择股票、ETF或基金标的，再开始 Stock Agent 分析。");
        }
        boolean containsDifferentSymbol = context.explicitSymbols().stream()
                .anyMatch(symbol -> !symbol.equals(context.contextSymbol()));
        if (containsDifferentSymbol) {
            return routeValidator.clarification(
                    context,
                    "SELECTED_INSTRUMENT_MISMATCH",
                    "当前工作区固定分析 " + context.contextSymbol()
                            + "。如需分析其他代码，请先切换标的。");
        }

        // 1. 先沿用三层分类，再按单标的工作区能力收缩可执行 Route。
        RouteDecision decision = route(question, context.contextSymbol(), false);
        if (isStockWorkspaceOutOfScope(decision)) {
            return routeValidator.clarification(
                    context,
                    "STOCK_WORKSPACE_ROUTE_OUT_OF_SCOPE",
                    "当前 Stock Agent 只处理已选单一标的。组合、多标的比较和板块分析"
                            + "将在对应工作区开放。");
        }
        return switch (decision.route()) {
            case GENERAL_CHAT, KNOWLEDGE_QA, EXTERNAL_RESEARCH,
                    MARKET_FACT, STOCK_DECISION, MARKET_CAUSAL_ANALYSIS,
                    NEED_CLARIFICATION -> decision;
            case PORTFOLIO_DECISION, QUANT_DECISION, SECTOR_ANALYSIS ->
                    routeValidator.clarification(
                            context,
                            "STOCK_WORKSPACE_ROUTE_OUT_OF_SCOPE",
                            "当前 Stock Agent 只处理已选单一标的。组合、多标的比较和板块分析"
                                    + "将在对应工作区开放。");
        };
    }

    private boolean isStockWorkspaceOutOfScope(RouteDecision decision) {
        if (decision.route() != RequestRoute.NEED_CLARIFICATION) {
            return false;
        }
        return switch (decision.reasonCode()) {
            case "PORTFOLIO_DATA_REQUIRED", "MISSING_QUANT_UNIVERSE",
                    "SECTOR_ROUTE_SYMBOL_CONFLICT", "SECTOR_REQUIRED",
                    "MIXED_SECTOR_TYPES" -> true;
            default -> false;
        };
    }

    private RouteCandidate localFallback(ChatIntent intent) {
        return switch (intent) {
            case GENERAL_CHAT -> candidate(
                    RequestRoute.GENERAL_CHAT, RouteSubjectType.NONE, null);
            case INVESTMENT_QA -> candidate(
                    RequestRoute.KNOWLEDGE_QA, RouteSubjectType.NONE, null);
            case PORTFOLIO_ANALYSIS -> candidate(
                    RequestRoute.PORTFOLIO_DECISION, RouteSubjectType.PORTFOLIO, null);
            case STOCK_ANALYSIS -> candidate(
                    RequestRoute.NEED_CLARIFICATION,
                    RouteSubjectType.STOCK,
                    "你是想查看当前行情和技术指标，还是需要买卖、仓位和风险决策分析？");
        };
    }

    private RouteCandidate candidate(RequestRoute route,
                                     RouteSubjectType subjectType,
                                     String ambiguityReason) {
        return new RouteCandidate(
                route,
                subjectType,
                List.of(),
                SectorType.UNKNOWN,
                true,
                0.65,
                ambiguityReason,
                route == RequestRoute.NEED_CLARIFICATION
                        ? RouteSource.CLARIFICATION
                        : RouteSource.LOCAL_FALLBACK);
    }
}
