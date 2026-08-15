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
 * Agent Run 的有序步骤实体，记录工具动作、Observation、策略拒绝与最终回答。
 */
@Data
@TableName(value = "public.agent_steps", autoResultMap = true)
public class AgentStep {

    @TableId(type = IdType.AUTO)
    private Long id;

    private UUID runId;

    private Integer stepNo;

    private String stepType;

    private String name;

    private String summary;

    /** 步骤结构化载荷，由 JsonbTypeHandler 与 jsonb 列互转。 */
    @TableField(typeHandler = JsonbTypeHandler.class)
    private Map<String, Object> payload;

    private OffsetDateTime createdAt;
}
