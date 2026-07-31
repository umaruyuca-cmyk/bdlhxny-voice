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
 * 会话摘要的可重建向量索引，完整消息仍以 conversation_history 为长期记忆真相源。
 */
@Data
@TableName(value = "public.conversation_episode_embeddings", autoResultMap = true)
public class ConversationEpisodeEmbedding {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String embeddingId;

    private Long conversationHistoryId;

    private Long userId;

    private String sessionId;

    private String symbol;

    private String content;

    /** 会话摘要向量，由 VectorTypeHandler 与 pgvector 列互转。 */
    @TableField(typeHandler = VectorTypeHandler.class)
    private float[] embedding;

    /** LangChain4j TextSegment 元数据，由 JsonbTypeHandler 与 jsonb 列互转。 */
    @TableField(typeHandler = JsonbTypeHandler.class)
    private Map<String, Object> metadata;

    private OffsetDateTime createdAt;

    /** 语义相似度与时间衰减的综合分，仅用于查询结果。 */
    @TableField(exist = false)
    private Double score;
}
