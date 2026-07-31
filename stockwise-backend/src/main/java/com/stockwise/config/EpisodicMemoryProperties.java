package com.stockwise.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * 长期情景记忆的检索与降级参数，集中约束召回数量、相似度和时间权重。
 */
@Data
@Component
@ConfigurationProperties(prefix = "stockwise.memory.episodic-vector")
public class EpisodicMemoryProperties {

    private boolean enabled = true;

    private int topK = 3;

    private double minSimilarity = 0.55;

    private int candidateMultiplier = 4;

    private double semanticWeight = 0.85;

    private double recencyWeight = 0.15;

    private int recencyHalfLifeDays = 30;

    private int recentFallbackLimit = 3;
}
