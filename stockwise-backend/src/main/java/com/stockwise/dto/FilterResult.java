package com.stockwise.dto;

import com.stockwise.entity.KnowledgeChunkWithScore;

import java.util.List;

/**
 * 知识质量过滤结果，承载保留的知识、检测到的冲突，以及是否命中（kept 非空）的标志。
 *
 * @param kept          过滤后保留的知识列表
 * @param conflicts     被判为冲突的知识对照描述，供日志与提示
 * @param retrievalHit  是否还有可用知识（Agent 据此决定 retrieval_hit 标志）
 */
public record FilterResult(
        List<KnowledgeChunkWithScore> kept,
        List<String> conflicts,
        boolean retrievalHit
) {
}
