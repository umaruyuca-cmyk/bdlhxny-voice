package com.stockwise.websearch.attention;

import com.stockwise.websearch.model.SearchPurpose;
import com.stockwise.websearch.model.SearchResult;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 验证外围关注代理只使用固定搜索结果字段并保持可复算。
 */
class ExternalAttentionAnalyzerTest {

    private final ExternalAttentionAnalyzer analyzer = new ExternalAttentionAnalyzer();

    @Test
    void calculatesCoverageAndRetailKeywordProxyWithoutInferringIdentity() {
        Instant now = Instant.parse("2026-08-01T08:00:00Z");
        List<SearchResult> results = List.of(
                result("1", "a.com", "半导体还能追吗", now.minusSeconds(86_400)),
                result("2", "b.com", "半导体行业观察", now.minusSeconds(172_800)),
                result("3", "c.com", "新手如何看板块轮动", null),
                result("4", "d.com", "半导体近期表现", now.minusSeconds(30L * 86_400)));

        AttentionSnapshot snapshot = analyzer.analyze(results, now);

        assertThat(snapshot.metric()).isEqualTo("search_evidence_attention_proxy");
        assertThat(snapshot.resultCount()).isEqualTo(4);
        assertThat(snapshot.distinctDomains()).isEqualTo(4);
        assertThat(snapshot.retailKeywordHits()).isEqualTo(2);
        assertThat(snapshot.retailKeywordRatio()).isEqualTo(0.5);
        assertThat(snapshot.confidence()).isEqualTo("medium");
        assertThat(snapshot.limitations()).anyMatch(value -> value.contains("不能识别用户身份"));
    }

    private SearchResult result(String id, String domain, String title, Instant publishedAt) {
        return new SearchResult(
                id,
                "attention-1",
                SearchPurpose.MARKET_ATTENTION,
                title,
                "https://" + domain + "/article",
                domain,
                "摘要",
                "WEB",
                "searxng",
                publishedAt,
                Instant.parse("2026-08-01T08:00:00Z"),
                0.9);
    }
}
