package com.bdlh.runtime.dto;

/**
 * 表示正式对话入口的结构化POST请求，避免消息和用户身份进入URL。
 *
 * @param sessionId  会话标识
 * @param mode       普通问答或 Stock Agent 模式
 * @param message    用户原始问题
 * @param instrument 当前可选分析标的
 */
public record ChatStreamRequest(
        String sessionId,
        ChatMode mode,
        String message,
        ChatInstrument instrument
) {
}
