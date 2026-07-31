package com.stockwise.memory;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/**
 * 表示 Redis 工作记忆中的一条强类型对话消息，避免上下文组装依赖动态 Map。
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record ConversationMessage(String role, String content) {

    public ConversationMessage {
        role = normalizeRole(role);
        content = content == null ? "" : content;
    }

    /**
     * 创建用户消息，统一角色名称。
     */
    public static ConversationMessage user(String content) {
        return new ConversationMessage("user", content);
    }

    /**
     * 创建助手消息，统一角色名称。
     */
    public static ConversationMessage assistant(String content) {
        return new ConversationMessage("assistant", content);
    }

    private static String normalizeRole(String role) {
        if ("assistant".equalsIgnoreCase(role)) {
            return "assistant";
        }
        return "user";
    }
}
