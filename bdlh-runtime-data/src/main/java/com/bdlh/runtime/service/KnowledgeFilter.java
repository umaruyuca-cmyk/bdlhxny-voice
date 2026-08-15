package com.bdlh.runtime.service;

import com.bdlh.runtime.dto.FilterResult;
import com.bdlh.runtime.entity.KnowledgeChunkWithScore;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 知识质量过滤器，实现 PRD Step 5 / 6.2。
 * 依次剔除低相似度、过期、低可信知识，并对同主题的冲突知识保留置信度更高者；全空则触发知识缺失模式。
 * 冲突检测当前用"同原始问题"的启发式，精确的语义矛盾判定可后续接入 DeepSeek。
 */
@Slf4j
@Service
public class KnowledgeFilter {

    /** 置信度门槛：低于此值的知识不参与回答，也不长期保留。 */
    private static final int MIN_CONFIDENCE = 50;

    private final double minSimilarity;

    public KnowledgeFilter(@Value("${bdlh_runtime.knowledge.min-similarity:0.55}") double minSimilarity) {
        this.minSimilarity = minSimilarity;
    }

    /**
     * 对检索召回的原始结果做三维过滤，返回保留列表、冲突记录与是否命中。
     */
    public FilterResult filter(List<KnowledgeChunkWithScore> raw) {
        List<KnowledgeChunkWithScore> kept = new ArrayList<>();
        List<String> conflicts = new ArrayList<>();
        // 1. 空召回直接判未命中
        if (raw == null || raw.isEmpty()) {
            return new FilterResult(kept, conflicts, false);
        }
        for (KnowledgeChunkWithScore chunk : raw) {
            Map<String, Object> meta = chunk.getMetadata();
            // 2. 低相似度结果不进入模型，避免 Top-K 为凑数量注入无关知识
            if (chunk.getScore() < minSimilarity) {
                continue;
            }
            // 3. 过期跳过（SQL 层已过滤，此处兜底防御脏数据）
            if (isExpired(meta)) {
                continue;
            }
            // 4. 低可信跳过
            if (confidenceOf(meta) < MIN_CONFIDENCE) {
                continue;
            }
            // 5. 冲突检测：与已保留知识同主题则视为冲突，保留置信度更高者
            KnowledgeChunkWithScore rival = findRival(chunk, kept);
            if (rival != null) {
                conflicts.add(chunk.getContent() + " ↔ " + rival.getContent());
                if (confidenceOf(meta) <= confidenceOf(rival.getMetadata())) {
                    continue;
                }
                kept.remove(rival);
            }
            kept.add(chunk);
        }
        // 6. 记录冲突便于排查
        if (!conflicts.isEmpty()) {
            log.warn("检测到知识冲突: {}", conflicts);
        }
        return new FilterResult(kept, conflicts, !kept.isEmpty());
    }

    /**
     * 判断知识是否已过有效期；expires_at 缺失或解析失败视为不过期。
     */
    private boolean isExpired(Map<String, Object> meta) {
        if (meta == null) {
            return false;
        }
        Object exp = meta.get("expires_at");
        if (exp == null) {
            return false;
        }
        try {
            return Instant.parse(String.valueOf(exp)).isBefore(Instant.now());
        } catch (Exception e) {
            return false;
        }
    }

    /**
     * 读取 metadata 中的置信度，兼容数字与字符串两种存储形态。
     */
    private int confidenceOf(Map<String, Object> meta) {
        if (meta == null) {
            return 0;
        }
        Object c = meta.get("confidence");
        if (c instanceof Number n) {
            return n.intValue();
        }
        try {
            return Integer.parseInt(String.valueOf(c));
        } catch (Exception e) {
            return 0;
        }
    }

    /**
     * 在已保留列表中查找与当前知识同主题（同原始问题）者，存在则视为冲突对手。
     */
    private KnowledgeChunkWithScore findRival(KnowledgeChunkWithScore chunk, List<KnowledgeChunkWithScore> kept) {
        String key = topicKey(chunk.getMetadata());
        if (key.isEmpty()) {
            return null;
        }
        for (KnowledgeChunkWithScore k : kept) {
            if (key.equals(topicKey(k.getMetadata()))) {
                return k;
            }
        }
        return null;
    }

    /**
     * 提取主题 key，用 metadata.problem 归一化；缺失则返回空串（不参与冲突判定）。
     */
    private String topicKey(Map<String, Object> meta) {
        if (meta == null) {
            return "";
        }
        Object p = meta.get("problem");
        return p == null ? "" : String.valueOf(p).trim().toLowerCase();
    }
}
