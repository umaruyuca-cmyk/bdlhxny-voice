package com.stockwise.dto;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonValue;

import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.UUID;

/**
 * 区分普通问答和 Stock Agent，使路由、会话与工具权限不再仅依赖模型判断。
 */
public enum ChatMode {
    GENERAL("general", "general"),
    STOCK_AGENT("stock", "stock");

    private final String value;
    private final String sessionPrefix;

    ChatMode(String value, String sessionPrefix) {
        this.value = value;
        this.sessionPrefix = sessionPrefix;
    }

    /**
     * 兼容前端小写模式值，未提供时由控制器根据是否存在标的决定兼容模式。
     */
    @JsonCreator
    public static ChatMode from(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String normalized = value.trim().toLowerCase(Locale.ROOT);
        return switch (normalized) {
            case "general", "direct_chat", "tool_agent" -> GENERAL;
            case "stock", "stock_agent", "stock_analysis" -> STOCK_AGENT;
            default -> throw new IllegalArgumentException("mode 仅支持 general 或 stock");
        };
    }

    /**
     * 生成固定长度的模式隔离会话标识，避免普通问答和股票分析共享 Redis 状态。
     */
    public String scopedSessionId(String clientSessionId) {
        UUID namespace = UUID.nameUUIDFromBytes(
                (sessionPrefix + ":" + clientSessionId).getBytes(StandardCharsets.UTF_8));
        return sessionPrefix + "_" + namespace;
    }

    @JsonValue
    public String value() {
        return value;
    }
}
