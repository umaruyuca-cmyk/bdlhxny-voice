package com.stockwise.service;

import com.stockwise.dto.ChatMode;
import com.stockwise.entity.ConversationSession;
import com.stockwise.mapper.ConversationSessionMapper;
import com.stockwise.memory.ConversationMessage;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * Agent 会话目录服务，统一维护标题、模式和最近更新时间，并从历史快照提供可恢复消息。
 */
@Service
public class ConversationSessionService {

    private static final int MAX_LIMIT = 50;

    private final ConversationSessionMapper sessionMapper;
    private final ConversationHistoryService historyService;

    public ConversationSessionService(ConversationSessionMapper sessionMapper,
                                      ConversationHistoryService historyService) {
        this.sessionMapper = sessionMapper;
        this.historyService = historyService;
    }

    /**
     * 创建或刷新会话目录，并保存本轮消息快照；快照失败不阻断已经完成的 Agent 回答。
     */
    public void saveTurn(Long userId,
                         String sessionId,
                         ChatMode mode,
                         String title,
                         List<ConversationMessage> messages) {
        ConversationSession session = new ConversationSession();
        session.setSessionId(sessionId);
        session.setUserId(userId);
        session.setMode(mode == null ? ChatMode.GENERAL.value() : mode.value());
        session.setTitle(normalizeTitle(title));
        session.setMessageCount(messages == null ? 0 : messages.size());
        session.setStatus("ACTIVE");
        sessionMapper.upsert(session);
        historyService.saveSnapshot(userId, sessionId, messages, null);
    }

    /**
     * 查询用户最近会话，支持按 Agent 模式筛选。
     */
    public List<ConversationSession> listRecent(Long userId, ChatMode mode, int limit) {
        int safeLimit = Math.max(1, Math.min(limit, MAX_LIMIT));
        return sessionMapper.selectRecent(userId, mode == null ? null : mode.value(), safeLimit);
    }

    /**
     * 查询用户拥有的会话及最新消息快照。
     */
    public ConversationDetail loadOwned(Long userId, String sessionId) {
        ConversationSession session = sessionMapper.selectOwned(userId, sessionId);
        if (session == null) {
            return null;
        }
        List<Object> messages = historyService.loadLatestMessages(userId, sessionId);
        return new ConversationDetail(session, messages);
    }

    private String normalizeTitle(String title) {
        String value = title == null ? "" : title.trim();
        if (value.isEmpty()) {
            return "新的研究";
        }
        return value.length() > 22 ? value.substring(0, 22) + "…" : value;
    }

    /**
     * 会话目录与消息快照的组合返回值。
     */
    public record ConversationDetail(ConversationSession session, List<Object> messages) {
    }
}
