package com.stockwise.websearch.model;

import java.util.List;

/**
 * 表示共享搜索服务的一次固定响应，允许部分任务成功和部分任务失败。
 */
public record WebSearchResponse(
        String requestId,
        String provider,
        List<SearchResult> results,
        List<SearchError> errors
) {
    public WebSearchResponse {
        results = results == null ? List.of() : List.copyOf(results);
        errors = errors == null ? List.of() : List.copyOf(errors);
    }
}
