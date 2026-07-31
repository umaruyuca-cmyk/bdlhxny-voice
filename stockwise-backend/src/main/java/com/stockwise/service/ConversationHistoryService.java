package com.stockwise.service;

import com.stockwise.entity.ConversationHistory;
import com.stockwise.mapper.ConversationHistoryMapper;
import com.stockwise.memory.ConversationMessage;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

/**
 * 对话历史中期记忆服务。
 * Redis 只存短期会话状态（30min TTL），本服务把完整会话归档到 PG conversation_history，支持跨会话回溯与新会话上下文加载。
 */
@Service
public class ConversationHistoryService {

    private final ConversationHistoryMapper mapper;

    public ConversationHistoryService(ConversationHistoryMapper mapper) {
        this.mapper = mapper;
    }

    /**
     * 归档一次完整会话：消息数组与摘要写入 PG，messages 以 JSONB 存储。
     */
    public ConversationHistory archive(Long userId,
                                       String sessionId,
                                       List<ConversationMessage> messages,
                                       String summary) {
        // 1. 构建历史实体，messages 走自定义 insertArchive 保证 jsonb 类型
        ConversationHistory h = new ConversationHistory();
        h.setUserId(userId);
        h.setSessionId(sessionId);
        h.setMessages(new ArrayList<Object>(messages));
        h.setSummary(summary);
        mapper.insertArchive(h);
        return h;
    }

    /**
     * 加载用户最近的若干条会话历史，供新会话作为上下文参考。
     */
    public List<ConversationHistory> loadRecent(Long userId, int limit) {
        // 1. 用参数化分页限制查询数量，避免把 limit 直接拼入 SQL。
        int safeLimit = Math.max(1, Math.min(limit, 20));
        return mapper.selectRecent(userId, safeLimit);
    }
}
