package com.stockwise.agent.routing;

import com.stockwise.agent.routing.SectorEntityResolver.ResolvedSector;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Optional;
import java.util.regex.Pattern;

/**
 * 仅识别能够唯一决定 Route 的高确定性句式，其他请求明确交给语义分类器。
 */
@Component
public class RuleBasedRouteResolver {

    private static final Pattern GREETING_PATTERN = Pattern.compile(
            "^(你好|您好|嗨|hi|hello|在吗|谢谢|感谢|帮助|你能做什么)[！!。.\\s]*$",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern MARKET_FACT_PATTERN = Pattern.compile(
            "(现在多少钱|当前价格|当前股价|现价|最新价|涨跌幅|日\\s*K|K线|k线|"
                    + "MA5|MA10|MA20|MA60|MACD|RSI|KDJ|均线|成交量|量比|技术指标)",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern STOCK_DECISION_PATTERN = Pattern.compile(
            "(能买吗|能不能买|适合买|买入|卖出|加仓|补仓|减仓|清仓|止损|止盈|"
                    + "持有吗|仓位建议|还能拿|要不要卖|走势分析)");
    private static final Pattern PORTFOLIO_PATTERN = Pattern.compile(
            "(我的持仓|持仓组合|整体持仓|组合风险|整体风险|整体仓位|仓位怎么调|"
                    + "持仓怎么调|调仓|月度资金分配)");
    private static final Pattern QUANT_PATTERN = Pattern.compile(
            "(ETF|etf|基金).*(轮动|排名|选哪|选择|比较|对比|目标权重)|"
                    + "(轮动|比较|对比).*(ETF|etf|基金)");
    private static final Pattern SECTOR_ATTENTION_PATTERN = Pattern.compile(
            "(讨论度|关注度|搜索热度|网上.*热|舆情热度|大众关注|散户热度|小白指数|宝妈指数)");
    private static final Pattern SECTOR_DECISION_PATTERN = Pattern.compile(
            "(能买吗|能不能买|值得买吗|未来|后续|到顶|见顶|还能追|买入|加仓|减仓|方向判断|投资建议)");
    private static final Pattern SECTOR_FACT_PATTERN = Pattern.compile(
            "(板块|行业|概念|热度|趋势|排名|资金流|资金流向|轮动|强不强|涨跌|换手|表现)");
    private static final Pattern SECTOR_RANKING_PATTERN = Pattern.compile(
            "(哪些板块|什么板块|板块排名|行业排名|最强板块|板块轮动)");
    private static final Pattern CAUSAL_EVENT_PATTERN = Pattern.compile(
            "(降息|加息|政策|公告|事件|关税|战争|制裁|财报|业绩|消息|国际局势)");
    private static final Pattern CAUSAL_EFFECT_PATTERN = Pattern.compile(
            "(有什么影响|影响多大|会影响|利好|利空|冲击|受益|承压|带来什么)");
    private static final Pattern PRICE_CAUSAL_PATTERN = Pattern.compile(
            "(为什么|为何|原因|怎么回事).*(上涨|下跌|涨停|跌停|大涨|大跌)|"
                    + "(上涨|下跌|涨停|跌停|大涨|大跌).*(为什么|为何|原因|怎么回事)");
    private static final Pattern EXTERNAL_PATTERN = Pattern.compile(
            "(最新|近期|最近|今天).*(政策|新闻|公告|消息|事件|LPR)|"
                    + "(政策|新闻|公告|消息|事件|LPR).*(最新|近期|最近|今天)",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern KNOWLEDGE_PATTERN = Pattern.compile(
            "(什么是|是什么意思|如何计算|怎么计算|有何区别|区别是什么|原理|定义)");

    private final SectorEntityResolver sectorResolver;

    @Autowired
    public RuleBasedRouteResolver(SectorEntityResolver sectorResolver) {
        this.sectorResolver = sectorResolver;
    }

    /**
     * 为不启动 Spring 容器的单元测试创建默认受控板块解析器。
     */
    public RuleBasedRouteResolver() {
        this(new SectorEntityResolver());
    }

    /**
     * 返回确定性命中的候选路由，未命中时由上层调用语义分类器。
     */
    public Optional<RouteCandidate> resolve(RoutingContext context) {
        String question = context.question();
        if (question.isBlank()) {
            return Optional.of(candidate(
                    RequestRoute.NEED_CLARIFICATION,
                    RouteSubjectType.NONE,
                    List.of(),
                    SectorType.UNKNOWN,
                    false,
                    "请描述你想查询或分析的问题。"));
        }
        if (GREETING_PATTERN.matcher(question).matches()) {
            return Optional.of(candidate(
                    RequestRoute.GENERAL_CHAT,
                    RouteSubjectType.NONE,
                    List.of(),
                    SectorType.UNKNOWN,
                    false,
                    null));
        }

        List<ResolvedSector> sectors = sectorResolver.resolve(question, List.of(), SectorType.UNKNOWN);
        List<String> sectorNames = sectors.stream().map(ResolvedSector::name).distinct().toList();
        SectorType sectorType = sectors.isEmpty() ? SectorType.UNKNOWN : sectors.get(0).type();
        boolean hasSymbol = !context.explicitSymbols().isEmpty() || context.contextSymbol() != null;
        boolean useContext = context.explicitSymbols().isEmpty() && context.contextSymbol() != null;

        // 1. 外部事件影响分析优先于普通板块或外部事实查询。
        if (hasSymbol && PRICE_CAUSAL_PATTERN.matcher(question).find()) {
            return Optional.of(candidate(
                    RequestRoute.MARKET_CAUSAL_ANALYSIS,
                    RouteSubjectType.STOCK,
                    List.of(),
                    SectorType.UNKNOWN,
                    useContext,
                    null));
        }
        if (CAUSAL_EVENT_PATTERN.matcher(question).find()
                && CAUSAL_EFFECT_PATTERN.matcher(question).find()) {
            RouteSubjectType subjectType = hasSymbol
                    ? RouteSubjectType.STOCK
                    : sectorNames.isEmpty() ? RouteSubjectType.MARKET : RouteSubjectType.SECTOR;
            return Optional.of(candidate(
                    RequestRoute.MARKET_CAUSAL_ANALYSIS,
                    subjectType,
                    sectorNames,
                    sectorType,
                    useContext,
                    null));
        }

        // 2. 多标的量化必须同时满足代码数量和明确的比较/轮动目标。
        if (context.explicitSymbols().size() >= 2 && QUANT_PATTERN.matcher(question).find()) {
            return Optional.of(candidate(
                    RequestRoute.QUANT_DECISION,
                    RouteSubjectType.ETF_POOL,
                    List.of(),
                    SectorType.UNKNOWN,
                    false,
                    null));
        }
        if (PORTFOLIO_PATTERN.matcher(question).find()) {
            return Optional.of(candidate(
                    RequestRoute.PORTFOLIO_DECISION,
                    RouteSubjectType.PORTFOLIO,
                    List.of(),
                    SectorType.UNKNOWN,
                    false,
                    null));
        }
        if (SECTOR_ATTENTION_PATTERN.matcher(question).find()) {
            return Optional.of(candidate(
                    RequestRoute.SECTOR_ATTENTION,
                    sectorNames.isEmpty() ? RouteSubjectType.MARKET : RouteSubjectType.SECTOR,
                    sectorNames,
                    sectorNames.isEmpty() ? SectorType.INDUSTRY : sectorType,
                    false,
                    null));
        }
        if (!sectorNames.isEmpty() && SECTOR_DECISION_PATTERN.matcher(question).find()) {
            return Optional.of(candidate(
                    RequestRoute.SECTOR_ANALYSIS,
                    RouteSubjectType.SECTOR,
                    sectorNames,
                    sectorType,
                    false,
                    null));
        }
        if (sectorNames.isEmpty() && SECTOR_RANKING_PATTERN.matcher(question).find()) {
            return Optional.of(candidate(
                    RequestRoute.SECTOR_FACT,
                    RouteSubjectType.MARKET,
                    List.of(),
                    SectorType.INDUSTRY,
                    false,
                    null));
        }
        if (!sectorNames.isEmpty() && SECTOR_FACT_PATTERN.matcher(question).find()) {
            return Optional.of(candidate(
                    RequestRoute.SECTOR_FACT,
                    RouteSubjectType.SECTOR,
                    sectorNames,
                    sectorType,
                    false,
                    null));
        }
        if (STOCK_DECISION_PATTERN.matcher(question).find() && hasSymbol) {
            return Optional.of(candidate(
                    RequestRoute.STOCK_DECISION,
                    RouteSubjectType.STOCK,
                    List.of(),
                    SectorType.UNKNOWN,
                    useContext,
                    null));
        }
        if (MARKET_FACT_PATTERN.matcher(question).find() && hasSymbol) {
            return Optional.of(candidate(
                    RequestRoute.MARKET_FACT,
                    RouteSubjectType.STOCK,
                    List.of(),
                    SectorType.UNKNOWN,
                    useContext,
                    null));
        }
        if (EXTERNAL_PATTERN.matcher(question).find()) {
            return Optional.of(candidate(
                    RequestRoute.EXTERNAL_RESEARCH,
                    hasSymbol ? RouteSubjectType.STOCK : RouteSubjectType.NONE,
                    sectorNames,
                    sectorType,
                    useContext,
                    null));
        }
        if (KNOWLEDGE_PATTERN.matcher(question).find()) {
            return Optional.of(candidate(
                    RequestRoute.KNOWLEDGE_QA,
                    RouteSubjectType.NONE,
                    List.of(),
                    SectorType.UNKNOWN,
                    false,
                    null));
        }
        return Optional.empty();
    }

    private RouteCandidate candidate(RequestRoute route,
                                     RouteSubjectType subjectType,
                                     List<String> sectors,
                                     SectorType sectorType,
                                     boolean useContextSymbol,
                                     String ambiguityReason) {
        return new RouteCandidate(
                route,
                subjectType,
                sectors,
                sectorType,
                useContextSymbol,
                route == RequestRoute.NEED_CLARIFICATION ? 1.0 : 0.99,
                ambiguityReason,
                route == RequestRoute.NEED_CLARIFICATION
                        ? RouteSource.CLARIFICATION
                        : RouteSource.REGEX);
    }
}
