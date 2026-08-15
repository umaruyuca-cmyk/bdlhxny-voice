package com.bdlh.runtime.websearch.attention;

import com.bdlh.runtime.websearch.model.SearchResult;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.Instant;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * 使用来源覆盖、独立域名、发布时间和零售关键词生成可复算外围关注代理。
 */
@Component
public class ExternalAttentionAnalyzer {

    private static final int EXPECTED_RESULTS = 5;
    private static final int EXPECTED_DOMAINS = 4;
    private static final Duration RECENT_WINDOW = Duration.ofDays(14);
    private static final List<String> RETAIL_KEYWORDS = List.of(
            "能买吗", "还能追", "上车", "抄底", "梭哈", "小白", "新手", "入门", "会不会涨");

    /**
     * 以当前时间计算外围关注代理，输出不依赖大模型判断。
     */
    public AttentionSnapshot analyze(List<SearchResult> results) {
        return analyze(results, Instant.now());
    }

    /**
     * 以指定时间计算外围关注代理，便于回放和确定性测试。
     */
    public AttentionSnapshot analyze(List<SearchResult> results, Instant now) {
        List<SearchResult> safeResults = results == null ? List.of() : results;
        Set<String> domains = new HashSet<>();
        int publishedCount = 0;
        int recentCount = 0;
        int keywordHits = 0;
        for (SearchResult result : safeResults) {
            if (result.domain() != null && !result.domain().isBlank()) {
                domains.add(result.domain().trim().toLowerCase(Locale.ROOT));
            }
            if (result.publishedAt() != null) {
                publishedCount++;
                Duration age = Duration.between(result.publishedAt(), now);
                if (!age.isNegative() && age.compareTo(RECENT_WINDOW) <= 0) {
                    recentCount++;
                }
            }
            String text = ((result.title() == null ? "" : result.title()) + " "
                    + (result.snippet() == null ? "" : result.snippet())).toLowerCase(Locale.ROOT);
            if (RETAIL_KEYWORDS.stream().anyMatch(text::contains)) {
                keywordHits++;
            }
        }

        // 1. 只按本次固定结果预算衡量证据覆盖，不能解释为互联网总讨论量。
        double coverageScore = boundedRatio(safeResults.size(), EXPECTED_RESULTS) * 100;
        double diversityScore = boundedRatio(domains.size(), EXPECTED_DOMAINS) * 100;
        double recentRatio = publishedCount == 0 ? 0 : (double) recentCount / publishedCount;
        double score = round(coverageScore * 0.45 + diversityScore * 0.35 + recentRatio * 100 * 0.20);
        double retailRatio = safeResults.isEmpty() ? 0 : (double) keywordHits / safeResults.size();
        String confidence = safeResults.size() >= 4 && domains.size() >= 3 && publishedCount >= 2
                ? "medium"
                : "low";
        return new AttentionSnapshot(
                "search_evidence_attention_proxy",
                score,
                level(score),
                safeResults.size(),
                domains.size(),
                round(recentRatio),
                keywordHits,
                round(retailRatio),
                confidence,
                List.of(
                        "搜索结果覆盖不等于真实搜索量或平台互动量",
                        "零售关键词命中不能识别用户身份、性别、家庭情况或投资经验",
                        "该指标只能辅助观察外围关注，不得替代结构化行情和资金数据"));
    }

    private double boundedRatio(int value, int expected) {
        return Math.min(1.0, Math.max(0.0, (double) value / expected));
    }

    private String level(double score) {
        if (score >= 75) {
            return "high";
        }
        if (score >= 45) {
            return "medium";
        }
        return "low";
    }

    private double round(double value) {
        return Math.round(value * 10_000.0) / 10_000.0;
    }
}
