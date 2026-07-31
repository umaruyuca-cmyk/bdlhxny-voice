package com.stockwise.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.stockwise.handler.JsonbTypeHandler;
import com.stockwise.handler.VectorTypeHandler;
import lombok.Data;

import java.time.OffsetDateTime;
import java.util.Map;

/**
 * 知识库单条知识实体，对应 knowledge_chunks 表。
 * 采用解决驱动型沉淀：embedding 是检索向量，metadata 承载 source/confidence/expires_at 等生命周期信息。
 * autoResultMap = true 让查询结果自动经 TypeHandler 把 vector/jsonb 列还原为 Java 类型。
 */
@Data
@TableName(value = "public.knowledge_chunks", autoResultMap = true)
public class KnowledgeChunk {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String content;

    /** pgvector 向量，由 VectorTypeHandler 与 vector 列互转。 */
    @TableField(typeHandler = VectorTypeHandler.class)
    private float[] embedding;

    /** 知识生命周期元数据，由 JsonbTypeHandler 与 jsonb 列互转。 */
    @TableField(typeHandler = JsonbTypeHandler.class)
    private Map<String, Object> metadata;

    private String status;

    private Integer version;

    private Long replacesId;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;
}
