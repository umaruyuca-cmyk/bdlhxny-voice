package com.bdlh.runtime.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.bdlh.runtime.handler.JsonbTypeHandler;
import lombok.Data;

import java.time.OffsetDateTime;
import java.util.Map;
import java.util.UUID;

/**
 * 用户结构化反馈实体，用于评估回答效果和追踪知识确认结果。
 */
@Data
@TableName(value = "public.user_feedback", autoResultMap = true)
public class UserFeedback {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long userId;

    private String sessionId;

    private UUID runId;

    private String feedbackType;

    private String message;

    @TableField(typeHandler = JsonbTypeHandler.class)
    private Map<String, Object> metadata;

    private OffsetDateTime createdAt;
}
