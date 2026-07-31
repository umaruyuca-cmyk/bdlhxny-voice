package com.stockwise.dto;

/**
 * Agent 对话请求，关联当前会话与报告版本。
 *
 * @param conversationId 会话唯一标识
 * @param symbol         标的代码
 * @param reportVersion  前端当前报告版本
 * @param message        用户输入
 */
public record ChatRequest(
        String conversationId,
        String symbol,
        int reportVersion,
        String message
) {
}
