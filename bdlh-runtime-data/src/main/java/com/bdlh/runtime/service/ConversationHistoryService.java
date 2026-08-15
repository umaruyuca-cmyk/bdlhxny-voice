package com.bdlh.runtime.service;

import com.bdlh.runtime.entity.ConversationHistory;
import com.bdlh.runtime.entity.ConversationSessionSnapshot;
import com.bdlh.runtime.mapper.ConversationHistoryMapper;
import com.bdlh.runtime.mapper.ConversationSessionSnapshotMapper;
import com.bdlh.runtime.memory.ConversationMessage;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

/**
 * 对话历史中期记忆服务。
 * Redis 只存短期会话状态（30min TTL），本服务把长期情景归档与可恢复快照分开保存，避免刷新会话时扫描重复历史。
 */
@Service
public class ConversationHistoryService {

    private final ConversationHistoryMapper mapper;
    private final ConversationSessionSnapshotMapper snapshotMapper;

    public ConversationHistoryService(ConversationHistoryMapper mapper,
                                      ConversationSessionSnapshotMapper snapshotMapper) {
        this.mapper = mapper;
        this.snapshotMapper = snapshotMapper;
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
    /**
     * 保存一次可恢复的会话消息快照，不触发长期向量归档，避免每轮对话重复建立情景索引。
     */
    public void saveSnapshot(Long userId,
                             String sessionId,
                             List<ConversationMessage> messages,
                             String summary) {
        if (messages == null || messages.isEmpty()) {
            return;
        }
        ConversationSessionSnapshot snapshot = new ConversationSessionSnapshot();
        snapshot.setSessionId(sessionId);
        snapshot.setUserId(userId);
        snapshot.setMessages(new ArrayList<Object>(messages));
        snapshot.setTokenCount(messages.stream()
                .mapToInt(message -> message.content() == null ? 0 : message.content().length())
                .sum());
        snapshotMapper.upsert(snapshot);
    }

    /**
     * 读取指定用户的最新消息快照，缺失时返回 null。
     */
    public List<Object> loadLatestMessages(Long userId, String sessionId) {
        ConversationSessionSnapshot snapshot = snapshotMapper.selectOwned(userId, sessionId);
        return snapshot == null || snapshot.getMessages() == null
                ? List.of()
                : snapshot.getMessages();
    }
}
