package com.stockwise.service;

import com.stockwise.dto.FilterResult;
import com.stockwise.entity.KnowledgeChunkWithScore;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 验证向量结果必须同时通过相似度与可信度门槛。
 */
class KnowledgeFilterTest {

    private final KnowledgeFilter filter = new KnowledgeFilter(0.55);

    @Test
    void shouldRejectLowSimilarityEvenWhenConfidenceIsHigh() {
        FilterResult result = filter.filter(List.of(chunk(0.54, 90, "主题A")));

        assertFalse(result.retrievalHit());
        assertTrue(result.kept().isEmpty());
    }

    @Test
    void shouldKeepRelevantTrustedKnowledge() {
        FilterResult result = filter.filter(List.of(chunk(0.78, 85, "主题A")));

        assertTrue(result.retrievalHit());
        assertEquals(1, result.kept().size());
    }

    @Test
    void shouldKeepHigherConfidenceItemWithinSameTopic() {
        FilterResult result = filter.filter(List.of(
                chunk(0.80, 60, "同一主题"),
                chunk(0.76, 90, "同一主题")
        ));

        assertEquals(1, result.kept().size());
        assertEquals(90, result.kept().get(0).getMetadata().get("confidence"));
        assertEquals(1, result.conflicts().size());
    }

    private KnowledgeChunkWithScore chunk(double score, int confidence, String problem) {
        KnowledgeChunkWithScore chunk = new KnowledgeChunkWithScore();
        chunk.setContent("测试知识-" + confidence);
        chunk.setScore(score);
        chunk.setMetadata(Map.of(
                "confidence", confidence,
                "problem", problem,
                "source", "resolved"
        ));
        return chunk;
    }
}
