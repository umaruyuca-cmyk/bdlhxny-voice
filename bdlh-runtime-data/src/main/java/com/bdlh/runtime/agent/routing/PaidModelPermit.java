package com.bdlh.runtime.agent.routing;

/**
 * 表示付费模型门禁的不可变判定结果和可审计原因码。
 */
public record PaidModelPermit(boolean allowed, String reasonCode) {
}
