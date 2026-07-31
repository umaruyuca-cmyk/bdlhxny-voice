package com.stockwise.websearch.planner;

import com.stockwise.agent.routing.RequestRoute;
import com.stockwise.agent.routing.RouteDecision;
import com.stockwise.websearch.model.SearchPurpose;
import com.stockwise.websearch.model.SearchTask;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.UUID;
import java.util.regex.Pattern;

/**
 * 将已确定的 Route 转换为最小搜索词，不把完整会话、持仓和成本发送到共享服务。
 */
@Component
public class LocalSearchPlanner {

    private static final Pattern PRIVATE_SEGMENT = Pattern.compile(
            "(我的成本|持仓成本|我的预算|账户余额|手机号|身份证)[：:为是]?\\s*[^，。；;\\s]*");
    private static final Pattern CONVERSATION_SCAFFOLD = Pattern.compile(
            "(请问|请|麻烦|帮我|给我|查一下|查询一下|搜索一下|搜一下|我想知道|我想了解|"
                    + "能不能|可以不可以|告诉我|关于|有哪些|是什么|怎么样|如何|是否|吗|呢)");

    /**
     * 为允许联网的 Route 生成最多一个初始任务，复杂拆分后续仍受任务预算约束。
     */
    public List<SearchTask> plan(RouteDecision decision, String question) {
        if (decision.route() == RequestRoute.MARKET_CAUSAL_ANALYSIS) {
            String symbol = decision.symbol();
            if (symbol != null && isPriceReasonQuestion(question)) {
                String direction = containsDown(question) ? "下跌" : "上涨";
                return List.of(task(
                        SearchPurpose.NEWS_CATALYST,
                        symbol + " 近期 " + direction + " 原因 新闻 公告",
                        symbol,
                        30,
                        List.of()));
            }
            String sanitized = sanitize(question);
            SearchPurpose purpose = purpose(sanitized);
            String subject = symbol != null
                    ? symbol
                    : decision.sectors().isEmpty()
                    ? "A股市场"
                    : String.join(" ", decision.sectors());
            String query = (subject + " " + minimalQuery(sanitized, purpose))
                    .replaceAll("\\s+", " ")
                    .trim();
            if (query.length() > 100) {
                query = query.substring(0, 100).trim();
            }
            return List.of(task(purpose,
                    query,
                    symbol,
                    purpose == SearchPurpose.POLICY_UPDATE ? 365 : 30,
                    preferredDomains(purpose)));
        }
        if (decision.route() == RequestRoute.EXTERNAL_RESEARCH) {
            String sanitized = sanitize(question);
            SearchPurpose purpose = purpose(sanitized);
            String query = minimalQuery(sanitized, purpose);
            return List.of(task(purpose, query, decision.symbol(),
                    purpose == SearchPurpose.POLICY_UPDATE ? 365 : 30,
                    preferredDomains(purpose)));
        }
        throw new IllegalArgumentException("当前 Route 不允许规划 WebSearch: " + decision.route());
    }

    private SearchTask task(SearchPurpose purpose,
                            String query,
                            String symbol,
                            int freshnessDays,
                            List<String> domains) {
        return new SearchTask("search-" + UUID.randomUUID(), purpose, query, symbol,
                freshnessDays, domains, 5);
    }

    private String sanitize(String question) {
        String normalized = question == null ? "" : question.replace('\u0000', ' ').trim();
        normalized = PRIVATE_SEGMENT.matcher(normalized).replaceAll("");
        return normalized.replaceAll("\\s+", " ").trim();
    }

    private String minimalQuery(String sanitized, SearchPurpose purpose) {
        String keywords = CONVERSATION_SCAFFOLD.matcher(sanitized).replaceAll(" ");
        keywords = keywords.replaceAll("[，。！？；、,.!?;:：]+", " ")
                .replaceAll("\\s+", " ")
                .trim();
        String suffix = switch (purpose) {
            case COMPANY_ANNOUNCEMENT -> "最新 公告";
            case POLICY_UPDATE -> "最新 政策 官方";
            case NEWS_CATALYST -> "近期 新闻";
            case KNOWLEDGE_VERIFY -> "资料 核验";
        };
        String query = (keywords + " " + suffix).replaceAll("\\s+", " ").trim();
        if (query.length() > 100) {
            query = query.substring(0, 100).trim();
        }
        if (query.length() < 2) {
            throw new IllegalArgumentException("无法从用户问题中生成最小搜索任务");
        }
        return query;
    }

    private SearchPurpose purpose(String query) {
        if (query.contains("公告") || query.contains("年报") || query.contains("季报")) {
            return SearchPurpose.COMPANY_ANNOUNCEMENT;
        }
        if (query.contains("政策") || query.contains("监管") || query.contains("法规")) {
            return SearchPurpose.POLICY_UPDATE;
        }
        if (query.contains("新闻") || query.contains("消息") || query.contains("事件")) {
            return SearchPurpose.NEWS_CATALYST;
        }
        return SearchPurpose.KNOWLEDGE_VERIFY;
    }

    private List<String> preferredDomains(SearchPurpose purpose) {
        return switch (purpose) {
            case COMPANY_ANNOUNCEMENT -> List.of("cninfo.com.cn", "sse.com.cn", "szse.cn", "bse.cn");
            case POLICY_UPDATE -> List.of("gov.cn", "csrc.gov.cn");
            default -> List.of();
        };
    }

    private boolean isPriceReasonQuestion(String question) {
        if (question == null) {
            return false;
        }
        boolean asksReason = question.contains("为什么")
                || question.contains("为何")
                || question.contains("原因")
                || question.contains("怎么回事");
        boolean hasDirection = question.contains("涨")
                || question.contains("跌")
                || question.contains("上挫")
                || question.contains("下挫");
        return asksReason && hasDirection;
    }

    private boolean containsDown(String question) {
        return question != null && (question.contains("跌") || question.contains("下挫"));
    }

}
