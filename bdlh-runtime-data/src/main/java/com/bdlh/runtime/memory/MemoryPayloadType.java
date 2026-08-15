package com.bdlh.runtime.memory;

/**
 * 表示需要路由的记忆载荷类型，调用方不能用自由文本决定存储位置。
 */
public enum MemoryPayloadType {
    SESSION_STATE,
    CONVERSATION_ARCHIVE,
    AGENT_RUN,
    USER_FEEDBACK,
    CONFIRMED_KNOWLEDGE,
    PORTFOLIO_POSITION,
    USER_FINANCIAL_CONFIG
}
