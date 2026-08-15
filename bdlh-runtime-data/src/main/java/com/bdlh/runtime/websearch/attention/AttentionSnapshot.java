package com.bdlh.runtime.websearch.attention;

import java.util.List;

/**
 * 表示基于有限搜索结果计算的外围关注代理，明确与真实搜索量和用户人数隔离。
 */
public record AttentionSnapshot(
        String metric,
        double score,
        String level,
        int resultCount,
        int distinctDomains,
        double recentResultRatio,
        int retailKeywordHits,
        double retailKeywordRatio,
        String confidence,
        List<String> limitations
) {
    public AttentionSnapshot {
        limitations = limitations == null ? List.of() : List.copyOf(limitations);
    }
}
