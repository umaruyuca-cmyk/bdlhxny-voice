package com.bdlh.runtime.agent.routing;

import com.bdlh.runtime.agent.routing.SectorEntityResolver.ResolvedSector;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 校验候选 Route 的实体来源和前置条件，并生成后续组件唯一可信的最终路由结果。
 */
@Component
public class DeterministicRouteValidator {

    private final RouteExecutionPolicyRegistry policyRegistry;
    private final SectorEntityResolver sectorResolver;

    public DeterministicRouteValidator(RouteExecutionPolicyRegistry policyRegistry,
                                       SectorEntityResolver sectorResolver) {
        this.policyRegistry = policyRegistry;
        this.sectorResolver = sectorResolver;
    }

    /**
     * 把规则或模型候选转换为满足固定策略的最终 RouteDecision。
     */
    public RouteDecision validate(RoutingContext context, RouteCandidate candidate) {
        if (candidate == null || candidate.route() == null) {
            return clarification(context, "INVALID_ROUTE_CANDIDATE", "无法识别你的分析目标，请补充说明。");
        }
        if (candidate.route() == RequestRoute.NEED_CLARIFICATION) {
            String message = candidate.ambiguityReason() == null || candidate.ambiguityReason().isBlank()
                    ? "请补充你想查询的标的、板块或分析目标。"
                    : candidate.ambiguityReason();
            return clarification(context, "SEMANTIC_AMBIGUOUS", message);
        }

        List<String> symbols = selectedSymbols(context, candidate);
        return switch (candidate.route()) {
            case GENERAL_CHAT -> decision(candidate, RouteSubjectType.NONE, List.of(), List.of(),
                    SectorType.UNKNOWN, "VALID_GENERAL_CHAT");
            case KNOWLEDGE_QA -> decision(candidate, RouteSubjectType.NONE, List.of(), List.of(),
                    SectorType.UNKNOWN, "VALID_KNOWLEDGE_QA");
            case EXTERNAL_RESEARCH -> decision(candidate,
                    symbols.size() == 1 ? RouteSubjectType.STOCK : RouteSubjectType.NONE,
                    symbols.size() <= 1 ? symbols : List.of(),
                    List.of(), SectorType.UNKNOWN, "VALID_EXTERNAL_RESEARCH");
            case MARKET_FACT -> singleSymbolDecision(
                    context, candidate, symbols, RequestRoute.MARKET_FACT, "VALID_MARKET_FACT");
            case SECTOR_FACT, SECTOR_ATTENTION, SECTOR_ANALYSIS ->
                    sectorDecision(context, candidate, false, symbols);
            case STOCK_DECISION -> singleSymbolDecision(
                    context, candidate, symbols, RequestRoute.STOCK_DECISION, "VALID_STOCK_DECISION");
            case PORTFOLIO_DECISION -> context.portfolioAvailable()
                    ? decision(candidate, RouteSubjectType.PORTFOLIO, List.of(), List.of(),
                    SectorType.UNKNOWN, "VALID_PORTFOLIO_DECISION")
                    : clarification(context, "PORTFOLIO_DATA_REQUIRED", "请先录入至少一条有效持仓。");
            case QUANT_DECISION -> symbols.size() >= 2
                    ? decision(candidate, RouteSubjectType.ETF_POOL, symbols, List.of(),
                    SectorType.UNKNOWN, "VALID_QUANT_DECISION")
                    : clarification(context, "MISSING_QUANT_UNIVERSE",
                    "请至少提供两个需要比较的6位ETF或基金代码。");
            case MARKET_CAUSAL_ANALYSIS -> causalDecision(context, candidate, symbols);
            case NEED_CLARIFICATION -> clarification(
                    context, "SEMANTIC_AMBIGUOUS", "请补充你想分析的具体目标。");
        };
    }

    /**
     * 构造分类器明确表示语义不清时的追问结果。
     */
    public RouteDecision clarification(RoutingContext context, String reasonCode, String message) {
        List<String> symbols = context == null ? List.of() : context.explicitSymbols();
        RouteExecutionPolicy policy = policyRegistry.get(RequestRoute.NEED_CLARIFICATION);
        return new RouteDecision(
                RequestRoute.NEED_CLARIFICATION,
                policy.compatibleIntent(),
                policy.modelPolicy(),
                symbols.size() == 1 ? RouteSubjectType.STOCK : RouteSubjectType.NONE,
                symbols.size() == 1 ? symbols : List.of(),
                List.of(),
                SectorType.UNKNOWN,
                reasonCode,
                RouteSource.CLARIFICATION,
                1.0,
                false,
                false,
                true,
                message);
    }

    private RouteDecision singleSymbolDecision(RoutingContext context,
                                               RouteCandidate candidate,
                                               List<String> symbols,
                                               RequestRoute route,
                                               String reasonCode) {
        if (symbols.size() != 1) {
            String message = route == RequestRoute.MARKET_FACT
                    ? "请提供一个需要查询行情或指标的6位标的代码。"
                    : "请提供一个需要决策分析的6位标的代码。";
            return clarification(context, "SINGLE_SYMBOL_REQUIRED", message);
        }
        return decision(candidate, RouteSubjectType.STOCK, symbols, List.of(),
                SectorType.UNKNOWN, reasonCode);
    }

    private RouteDecision sectorDecision(RoutingContext context,
                                         RouteCandidate candidate,
                                         boolean causal,
                                         List<String> symbols) {
        if (!symbols.isEmpty()) {
            return clarification(context, "SECTOR_ROUTE_SYMBOL_CONFLICT",
                    "当前问题同时包含代码和板块目标，请说明要分析具体标的还是整个板块。");
        }
        List<ResolvedSector> resolved = sectorResolver.resolve(
                context.question(), candidate.sectorMentions(), candidate.sectorType());
        if (resolved.isEmpty()) {
            if (!causal && candidate.subjectType() == RouteSubjectType.MARKET
                    && candidate.sectorType() != SectorType.UNKNOWN) {
                return decision(candidate, RouteSubjectType.MARKET, List.of(), List.of(),
                        candidate.sectorType(), "VALID_SECTOR_RANKING");
            }
            return clarification(context, "SECTOR_REQUIRED", "请说明需要分析的行业或概念板块。");
        }
        SectorType type = resolved.get(0).type();
        boolean mixedTypes = resolved.stream().anyMatch(value -> value.type() != type);
        if (mixedTypes) {
            return clarification(context, "MIXED_SECTOR_TYPES",
                    "问题同时包含行业和概念板块，请分开提问以便核验数据。");
        }
        List<String> names = resolved.stream().map(ResolvedSector::name).distinct().toList();
        String reason = causal
                ? "VALID_SECTOR_CAUSAL_ANALYSIS"
                : switch (candidate.route()) {
                    case SECTOR_FACT -> "VALID_SECTOR_FACT";
                    case SECTOR_ATTENTION -> "VALID_SECTOR_ATTENTION";
                    default -> "VALID_SECTOR_ANALYSIS";
                };
        return decision(candidate, RouteSubjectType.SECTOR, List.of(), names, type, reason);
    }

    private RouteDecision causalDecision(RoutingContext context,
                                         RouteCandidate candidate,
                                         List<String> symbols) {
        if (symbols.size() == 1) {
            return decision(candidate, RouteSubjectType.STOCK, symbols, List.of(),
                    SectorType.UNKNOWN, "VALID_STOCK_CAUSAL_ANALYSIS");
        }
        if (symbols.size() > 1) {
            return clarification(context, "CAUSAL_SINGLE_SUBJECT_REQUIRED",
                    "因果分析暂时只支持一个具体标的或一个板块，请缩小分析范围。");
        }
        RouteDecision sector = sectorDecision(context, candidate, true, symbols);
        if (sector.route() != RequestRoute.NEED_CLARIFICATION) {
            return sector;
        }
        if (candidate.subjectType() == RouteSubjectType.MARKET
                || containsMarketSubject(context.question())) {
            return decision(candidate, RouteSubjectType.MARKET, List.of(), List.of(),
                    SectorType.INDUSTRY, "VALID_MARKET_CAUSAL_ANALYSIS");
        }
        return clarification(context, "CAUSAL_SUBJECT_REQUIRED",
                "请说明该事件影响的具体股票、板块或整体市场。");
    }

    private List<String> selectedSymbols(RoutingContext context, RouteCandidate candidate) {
        if (!context.explicitSymbols().isEmpty()) {
            return context.explicitSymbols();
        }
        if (candidate.useContextSymbol() && context.contextSymbol() != null) {
            return List.of(context.contextSymbol());
        }
        return List.of();
    }

    private RouteDecision decision(RouteCandidate candidate,
                                   RouteSubjectType subjectType,
                                   List<String> symbols,
                                   List<String> sectors,
                                   SectorType sectorType,
                                   String reasonCode) {
        RouteExecutionPolicy policy = policyRegistry.get(candidate.route());
        return new RouteDecision(
                candidate.route(),
                policy.compatibleIntent(),
                policy.modelPolicy(),
                subjectType,
                symbols,
                sectors,
                sectorType,
                reasonCode,
                candidate.source(),
                clamp(candidate.reportedConfidence()),
                !policy.allowedSkillCommands().isEmpty(),
                policy.webSearchRequired(),
                false,
                null);
    }

    private boolean containsMarketSubject(String question) {
        return question != null
                && (question.contains("A股")
                || question.contains("大盘")
                || question.contains("市场")
                || question.contains("股市"));
    }

    private double clamp(double value) {
        return Math.max(0.0, Math.min(1.0, value));
    }
}
