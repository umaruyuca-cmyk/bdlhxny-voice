package com.bdlh.runtime.agent.routing;

import com.bdlh.runtime.llm.ChatIntent;

import java.util.List;

/**
 * 保存代码可审计的路由结果，使后续执行器无需重新解释用户意图。
 */
public record RouteDecision(
        RequestRoute route,
        ChatIntent compatibleIntent,
        ModelPolicy modelPolicy,
        RouteSubjectType subjectType,
        List<String> symbols,
        List<String> sectors,
        SectorType sectorType,
        String reasonCode,
        RouteSource routeSource,
        double confidence,
        boolean requiresMarketData,
        boolean requiresExternalEvidence,
        boolean needsClarification,
        String clarification
) {

    public RouteDecision {
        symbols = symbols == null ? List.of() : List.copyOf(symbols);
        sectors = sectors == null ? List.of() : List.copyOf(sectors);
        subjectType = subjectType == null ? RouteSubjectType.NONE : subjectType;
        sectorType = sectorType == null ? SectorType.UNKNOWN : sectorType;
        routeSource = routeSource == null ? RouteSource.CLARIFICATION : routeSource;
    }

    /**
     * 将内部细分 Route 映射为对外稳定的三种业务执行路径。
     */
    public BusinessRoute businessRoute() {
        return switch (route) {
            case GENERAL_CHAT, KNOWLEDGE_QA, NEED_CLARIFICATION -> BusinessRoute.DIRECT_CHAT;
            case EXTERNAL_RESEARCH -> BusinessRoute.TOOL_AGENT;
            default -> BusinessRoute.STOCK_ANALYSIS;
        };
    }

    /**
     * 兼容旧调用点的单代码构造器，迁移期间仍由新访问器提供统一语义。
     */
    public RouteDecision(RequestRoute route,
                         ChatIntent compatibleIntent,
                         ModelPolicy modelPolicy,
                         String symbol,
                         String reasonCode,
                         double confidence,
                         boolean requiresMarketData,
                         boolean requiresExternalEvidence,
                         boolean needsClarification,
                         String clarification) {
        this(
                route,
                compatibleIntent,
                modelPolicy,
                inferSubject(route, symbol),
                symbol == null ? List.of() : List.of(symbol),
                List.of(),
                SectorType.UNKNOWN,
                reasonCode,
                needsClarification ? RouteSource.CLARIFICATION : RouteSource.REGEX,
                confidence,
                requiresMarketData,
                requiresExternalEvidence,
                needsClarification,
                clarification);
    }

    /**
     * 返回单标的 Route 的主代码，非单标的 Route 返回 null。
     */
    public String primarySymbol() {
        return symbols.size() == 1 ? symbols.get(0) : null;
    }

    /**
     * 兼容现有调用点读取单一代码，新代码应优先使用 primarySymbol 或 symbols。
     */
    public String symbol() {
        return primarySymbol();
    }

    private static RouteSubjectType inferSubject(RequestRoute route, String symbol) {
        if (symbol != null) {
            return RouteSubjectType.STOCK;
        }
        return switch (route) {
            case PORTFOLIO_DECISION -> RouteSubjectType.PORTFOLIO;
            case QUANT_DECISION -> RouteSubjectType.ETF_POOL;
            case SECTOR_FACT, SECTOR_ATTENTION, SECTOR_ANALYSIS -> RouteSubjectType.SECTOR;
            default -> RouteSubjectType.NONE;
        };
    }
}
