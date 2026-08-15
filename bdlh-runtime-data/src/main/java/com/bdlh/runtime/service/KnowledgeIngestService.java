package com.bdlh.runtime.service;

import com.bdlh.runtime.dto.IngestResult;
import com.bdlh.runtime.entity.KnowledgeChunk;
import com.bdlh.runtime.llm.EmbeddingService;
import com.bdlh.runtime.mapper.KnowledgeChunkMapper;
import com.bdlh.runtime.skill.KnowledgeCandidate;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 知识入库服务，实现 PRD Step 12-14。
 * 对单条候选知识：生成正式向量 → 与库内已有知识去重（>0.92 判重）→ 入库；置信度低于 50 直接拒绝。
 */
@Service
public class KnowledgeIngestService {

    /** 去重阈值：与已有知识的余弦相似度超过此值视为重复，跳过入库。 */
    private static final double DEDUP_THRESHOLD = 0.92;
    private static final int MIN_CONFIDENCE = 50;

    private final EmbeddingService embeddingService;
    private final KnowledgeChunkMapper knowledgeChunkMapper;
    private final String embeddingModel;

    public KnowledgeIngestService(EmbeddingService embeddingService,
                                  KnowledgeChunkMapper knowledgeChunkMapper,
                                  @Value("${bdlh_runtime.embedding.model:text-embedding-v4}") String embeddingModel) {
        this.embeddingService = embeddingService;
        this.knowledgeChunkMapper = knowledgeChunkMapper;
        this.embeddingModel = embeddingModel;
    }

    /**
     * 处理一条候选知识：门槛与去重校验通过后生成正式向量并入库。
     *
     * @param candidate 用户确认的候选知识
     * @param problem   原始问题，记入 metadata 供后续冲突检测的主题 key
     * @param userId    贡献者
     */
    public IngestResult ingest(KnowledgeCandidate candidate, String problem, Long userId) {
        Integer confidence = candidate.confidence();
        // 1. 低置信度直接拒绝（只有解决问题后才入库，门槛更严）
        if (confidence == null || confidence < MIN_CONFIDENCE) {
            return new IngestResult("low_confidence", "confidence=" + confidence);
        }
        // 2. 生成正式向量，查库内最大相似度判定重复
        float[] vec = embeddingService.embed(candidate.content());
        String vecStr = embeddingService.toVectorString(vec);
        double topSim = knowledgeChunkMapper.findTopSimilarity(vecStr);
        if (topSim > DEDUP_THRESHOLD) {
            return new IngestResult("duplicate", "max_similarity=" + topSim);
        }
        // 3. 构建实体并入库
        KnowledgeChunk chunk = new KnowledgeChunk();
        chunk.setContent(candidate.content());
        chunk.setEmbedding(vec);
        chunk.setMetadata(buildMetadata(candidate, problem, userId, confidence));
        chunk.setStatus("active");
        chunk.setVersion(1);
        knowledgeChunkMapper.insertKnowledge(chunk);
        return new IngestResult("ingested", "id=" + chunk.getId());
    }

    /**
     * 组装入库元数据：source/problem/confidence/tags/user_id。
     */
    private Map<String, Object> buildMetadata(KnowledgeCandidate c, String problem, Long userId, int confidence) {
        Map<String, Object> meta = new HashMap<>();
        // 1. 来源标记为"已解决问题沉淀"
        meta.put("source", "resolved");
        // 2. 原始问题，作为后续冲突检测的主题 key
        meta.put("problem", problem);
        // 3. 置信度与分类标签
        meta.put("confidence", confidence);
        meta.put("embedding_model", embeddingModel);
        meta.put("embedded_at", Instant.now().toString());
        List<String> tags = c.tags();
        if (tags != null && !tags.isEmpty()) {
            meta.put("tags", tags);
        }
        // 4. 贡献者
        if (userId != null) {
            meta.put("user_id", "u_" + userId);
        }
        return meta;
    }
}
