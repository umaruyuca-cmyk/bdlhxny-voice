package com.stockwise.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.stockwise.entity.ConversationEpisodeEmbedding;
import org.apache.ibatis.annotations.Param;

import java.util.Collection;
import java.util.List;

/**
 * 长期情景记忆向量索引的数据访问层，负责幂等写入、用户隔离检索和索引删除。
 */
public interface ConversationEpisodeEmbeddingMapper extends BaseMapper<ConversationEpisodeEmbedding> {

    /**
     * 幂等写入会话摘要索引，重复归档编号只更新可重建的索引内容。
     */
    int upsertEpisode(ConversationEpisodeEmbedding episode);

    /**
     * 按用户、可选标的、语义相似度和时间衰减检索相关会话摘要。
     */
    List<ConversationEpisodeEmbedding> searchRelevant(
            @Param("vec") String vec,
            @Param("userId") Long userId,
            @Param("symbol") String symbol,
            @Param("topK") int topK,
            @Param("candidateLimit") int candidateLimit,
            @Param("minSimilarity") double minSimilarity,
            @Param("semanticWeight") double semanticWeight,
            @Param("recencyWeight") double recencyWeight,
            @Param("recencyHalfLifeDays") int recencyHalfLifeDays);

    /**
     * 按 LangChain4j embeddingId 删除指定的可重建索引。
     */
    int deleteByEmbeddingId(@Param("embeddingId") String embeddingId);

    /**
     * 批量删除指定的可重建索引。
     */
    int deleteByEmbeddingIds(@Param("embeddingIds") Collection<String> embeddingIds);
}
