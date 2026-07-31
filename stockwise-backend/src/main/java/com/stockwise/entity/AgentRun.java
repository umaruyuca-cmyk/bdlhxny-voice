package com.stockwise.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * Agent 单次 Skill 推理运行实体，保存生命周期、版本、预算与最终结果。
 */
@Data
@TableName("public.agent_runs")
public class AgentRun {

    @TableId(type = IdType.INPUT)
    private UUID runId;

    private Long userId;

    private String sessionId;

    private String intent;

    private String skillName;

    private String skillVersion;

    private String status;

    private String requestText;

    private String finalAnswer;

    private Integer maxToolCalls;

    private Integer toolCallCount;

    private String errorMessage;

    private OffsetDateTime startedAt;

    private OffsetDateTime completedAt;
}
