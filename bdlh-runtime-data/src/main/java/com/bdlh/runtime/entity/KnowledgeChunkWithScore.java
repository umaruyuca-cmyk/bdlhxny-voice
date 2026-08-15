package com.bdlh.runtime.entity;

import lombok.Data;
import lombok.EqualsAndHashCode;

/**
 * 带相似度 score 的知识检索结果视图，仅用于向量检索返回，不映射任何表。
 */
@Data
@EqualsAndHashCode(callSuper = true)
public class KnowledgeChunkWithScore extends KnowledgeChunk {

    private double score;
}
