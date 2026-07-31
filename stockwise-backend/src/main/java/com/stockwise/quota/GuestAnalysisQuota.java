package com.stockwise.quota;

/**
 * 表示游客分析次数闸门的当前结果，供编排器和前端使用。
 */
public record GuestAnalysisQuota(
        boolean applicable,
        boolean allowed,
        int limit,
        int used,
        int remaining
) {

    /**
     * 返回不需要游客配额检查的结果。
     */
    public static GuestAnalysisQuota notApplicable() {
        return new GuestAnalysisQuota(false, true, 0, 0, 0);
    }
}
