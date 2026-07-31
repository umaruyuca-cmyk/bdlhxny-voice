package com.stockwise.websearch.model;

import java.util.List;

/**
 * 表示 StockWise 内部的领域搜索任务，转换到共享协议时会移除 symbol。
 */
public record SearchTask(
        String taskId,
        SearchPurpose purpose,
        String query,
        String symbol,
        Integer freshnessDays,
        List<String> preferredDomains,
        Integer maxResults
) {
    public SearchTask {
        preferredDomains = preferredDomains == null ? List.of() : List.copyOf(preferredDomains);
    }
}
