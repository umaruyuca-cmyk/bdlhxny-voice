package com.stockwise.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.stockwise.entity.ConversationSession;
import org.apache.ibatis.annotations.Param;

import java.util.List;

/**
 * Agent 会话目录数据访问层。
 * 目录只负责列表和权限范围，完整消息由 ConversationHistoryMapper 读取。
 */
public interface ConversationSessionMapper extends BaseMapper<ConversationSession> {

    /**
     * 创建或更新会话目录，保证首条消息和后续消息都能刷新标题与更新时间。
     */
    int upsert(ConversationSession session);

    /**
     * 按用户和 Agent 模式查询最近会话。
     */
    List<ConversationSession> selectRecent(
            @Param("userId") Long userId,
            @Param("mode") String mode,
            @Param("limit") int limit);

    /**
     * 按用户读取单个会话，避免通过 sessionId 越权读取其他用户目录。
     */
    ConversationSession selectOwned(
            @Param("userId") Long userId,
            @Param("sessionId") String sessionId);
}
