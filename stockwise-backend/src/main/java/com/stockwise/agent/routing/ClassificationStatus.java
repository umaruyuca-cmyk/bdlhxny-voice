package com.stockwise.agent.routing;

/**
 * 区分语义分类成功、问题本身不明确和外部分类器不可用三种状态。
 */
public enum ClassificationStatus {
    CLASSIFIED,
    AMBIGUOUS,
    UNAVAILABLE
}
