package com.bdlh.runtime.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.bdlh.runtime.handler.JsonbTypeHandler;
import lombok.Data;

import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * 工具执行审计实体，关联 Action 与 Observation 并记录耗时和错误。
 */
@Data
@TableName(value = "public.tool_executions", autoResultMap = true)
public class ToolExecution {

    @TableId(type = IdType.AUTO)
    private Long id;

    private UUID runId;

    private Integer callStepNo;

    private Integer observationStepNo;

    private String toolName;

    /** 模型提供的工具参数，按 JSONB 保存。 */
    @TableField(typeHandler = JsonbTypeHandler.class)
    private Object argumentJson;

    /** 工具返回的结构化 Observation，非 JSON 文本会包装为 raw 字段。 */
    @TableField(typeHandler = JsonbTypeHandler.class)
    private Object observationJson;

    private String status;

    private Long durationMs;

    private String errorCode;

    private String errorMessage;

    private OffsetDateTime startedAt;

    private OffsetDateTime completedAt;
}
