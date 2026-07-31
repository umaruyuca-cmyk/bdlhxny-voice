package com.stockwise.agent.routing;

/**
 * 保存语义分类调用状态，避免把语义不确定错误降级为低级分类覆盖。
 */
public record ClassificationResult(
        ClassificationStatus status,
        RouteCandidate candidate,
        String detail
) {

    /**
     * 构造成功分类结果。
     */
    public static ClassificationResult classified(RouteCandidate candidate) {
        return new ClassificationResult(ClassificationStatus.CLASSIFIED, candidate, null);
    }

    /**
     * 构造语义不明确结果。
     */
    public static ClassificationResult ambiguous(String detail) {
        return new ClassificationResult(ClassificationStatus.AMBIGUOUS, null, detail);
    }

    /**
     * 构造分类服务不可用结果。
     */
    public static ClassificationResult unavailable(String detail) {
        return new ClassificationResult(ClassificationStatus.UNAVAILABLE, null, detail);
    }
}
