package com.bdlh.runtime.agent.routing;

/**
 * 汇总标准化外部证据的充分性，不向付费门禁暴露 Provider 原始响应。
 */
public record EvidenceBundle(
        boolean searchAttempted,
        boolean sufficient,
        int resultCount,
        int distinctDomains,
        int authoritativeSourceCount
) {
    public static EvidenceBundle notRequired() {
        return new EvidenceBundle(false, true, 0, 0, 0);
    }
}
