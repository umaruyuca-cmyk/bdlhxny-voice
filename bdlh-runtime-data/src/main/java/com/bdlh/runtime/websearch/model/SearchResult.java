package com.bdlh.runtime.websearch.model;

import java.time.Instant;

/**
 * 表示已由共享 Wrapper 清洗的外部证据，业务层不接触 SearXNG 原始 JSON。
 */
public record SearchResult(
        String resultId,
        String taskId,
        SearchPurpose purpose,
        String title,
        String url,
        String domain,
        String snippet,
        String sourceType,
        String provider,
        Instant publishedAt,
        Instant retrievedAt,
        Double relevanceScore
) {
}
