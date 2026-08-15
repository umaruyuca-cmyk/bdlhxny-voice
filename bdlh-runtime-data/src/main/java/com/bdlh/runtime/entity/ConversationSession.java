package com.bdlh.runtime.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.OffsetDateTime;

/**
 * Agent 会话目录实体，保存左侧会话列表所需的轻量元数据。
 * 完整消息仍由 conversation_history 保存，避免把会话目录和上下文真相源混为一体。
 */
@Data
@TableName("public.conversation_sessions")
public class ConversationSession {

    @TableId
    private String sessionId;

    private Long userId;

    private String mode;

    private String title;

    private Integer messageCount;

    private String status;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;
}
