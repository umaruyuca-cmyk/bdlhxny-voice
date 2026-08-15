package com.bdlh.runtime.entity;

import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.bdlh.runtime.handler.JsonbTypeHandler;
import lombok.Data;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * 保存会话当前可恢复消息的最新快照，避免每轮把完整消息重复追加到历史归档表。
 */
@Data
@TableName(value = "public.conversation_session_snapshots", autoResultMap = true)
public class ConversationSessionSnapshot {

    @TableId
    private String sessionId;

    private Long userId;

    @TableField(typeHandler = JsonbTypeHandler.class)
    private List<Object> messages;

    private Integer tokenCount;

    private OffsetDateTime updatedAt;
}
