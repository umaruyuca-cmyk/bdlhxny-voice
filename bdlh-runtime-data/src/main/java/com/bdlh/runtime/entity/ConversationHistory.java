package com.bdlh.runtime.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.bdlh.runtime.handler.JsonbTypeHandler;
import lombok.Data;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * 对话历史实体（中期记忆），对应 conversation_history 表。
 * messages 以 JSONB 存储完整消息数组，超长时用 summary 字段保存压缩摘要。
 */
@Data
@TableName(value = "public.conversation_history", autoResultMap = true)
public class ConversationHistory {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long userId;

    private String sessionId;

    /** 完整对话消息数组，由 JsonbTypeHandler 与 jsonb 列互转。 */
    @TableField(typeHandler = JsonbTypeHandler.class)
    private List<Object> messages;

    private String summary;

    private Integer tokenCount;

    private OffsetDateTime createdAt;
}
