package com.stockwise.websearch.validation;

import com.stockwise.agent.routing.EvidenceBundle;
import com.stockwise.agent.routing.RequestRoute;
import com.stockwise.websearch.model.SearchResult;
import org.springframework.stereotype.Component;

import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * 按 Route 判断标准化搜索结果是否足够支撑本地回答或付费综合归因。
 */
@Component
public class EvidenceValidator {

    /**
     * 只使用来源数量和类型进行确定性判断，不让模型自行宣布证据充分。
     */
    public EvidenceBundle validate(RequestRoute route, List<SearchResult> results) {
        List<SearchResult> safeResults = results == null ? List.of() : results;
        Set<String> domains = new HashSet<>();
        int authoritative = 0;
        for (SearchResult result : safeResults) {
            if (result.domain() != null && !result.domain().isBlank()) {
                domains.add(result.domain());
            }
            if ("OFFICIAL".equalsIgnoreCase(result.sourceType())) {
                authoritative++;
            }
        }
        boolean sufficient = route == RequestRoute.MARKET_CAUSAL_ANALYSIS
                ? safeResults.size() >= 2 && domains.size() >= 2
                : !safeResults.isEmpty();
        return new EvidenceBundle(true, sufficient, safeResults.size(), domains.size(), authoritative);
    }
}
