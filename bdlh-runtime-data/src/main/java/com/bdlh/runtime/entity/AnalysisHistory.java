package com.bdlh.runtime.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.bdlh.runtime.handler.JsonbTypeHandler;
import lombok.Data;

import java.time.OffsetDateTime;
import java.util.Map;

/**
 * 分析结果历史实体，对应 analysis_history 表，用于审计与回溯历次分析结果。
 */
@Data
@TableName(value = "public.analysis_history", autoResultMap = true)
public class AnalysisHistory {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long userId;

    private String type;

    private String code;

    /** 分析结果 JSON，由 JsonbTypeHandler 与 jsonb 列互转。 */
    @TableField(typeHandler = JsonbTypeHandler.class)
    private Map<String, Object> resultJson;

    private Integer tokenUsed;

    private OffsetDateTime createdAt;
}
