package com.bdlh.runtime.service;

import com.bdlh.runtime.entity.KnowledgeChunkWithScore;
import com.bdlh.runtime.llm.EmbeddingService;
import com.bdlh.runtime.mapper.KnowledgeChunkMapper;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 知识向量检索服务，实现 PRD Step 3-4。
 * 生成临时向量（仅本次检索用、不落库）检索 Top-K 相似知识；SQL 层已过滤 active 与过期，冲突/可信度过滤留给 Step 5。
 */
@Service
public class KnowledgeRetrievalService {

    private final EmbeddingService embeddingService;
    private final KnowledgeChunkMapper knowledgeChunkMapper;

    public KnowledgeRetrievalService(EmbeddingService embeddingService, KnowledgeChunkMapper knowledgeChunkMapper) {
        this.embeddingService = embeddingService;
        this.knowledgeChunkMapper = knowledgeChunkMapper;
    }

    /**
     * 用问题文本检索最相似的 Top-K 知识，返回带相似度 score 的结果。
     *
     * @param question 用户原始问题
     * @param topK     返回条数，一般取 5
     */
    public List<KnowledgeChunkWithScore> search(String question, int topK) {
        if (question == null || question.isBlank()) {
            return List.of();
        }
        int safeTopK = Math.max(1, Math.min(topK, 50));
        // 1. 生成临时向量：仅活在本次调用，绝不写入数据库（临时/正式向量分离的核心）
        float[] vec = embeddingService.embed(question);
        // 2. 转成 pgvector 文本，作为检索 SQL 的入参
        String vecStr = embeddingService.toVectorString(vec);
        // 3. 检索 Top-K：ORDER BY embedding <=> vec 命中 ivfflat 索引，SQL 层已排除失效知识
        return knowledgeChunkMapper.searchByVector(vecStr, safeTopK);
    }
}
