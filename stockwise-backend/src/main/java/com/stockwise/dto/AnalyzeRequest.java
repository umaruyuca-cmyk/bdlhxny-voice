package com.stockwise.dto;

/**
 * 重新分析请求，指定标的、时区与缓存策略。
 *
 * @param symbol       标的代码
 * @param timezone     固定 Asia/Shanghai
 * @param forceRefresh 是否绕过缓存重新获取行情
 */
public record AnalyzeRequest(
        String symbol,
        String timezone,
        boolean forceRefresh
) {
}
