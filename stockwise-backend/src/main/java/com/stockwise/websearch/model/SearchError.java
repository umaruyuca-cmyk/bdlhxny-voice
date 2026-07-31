package com.stockwise.websearch.model;

/**
 * 表示单个搜索任务的安全错误摘要，不包含 Token 和 Provider 原始响应。
 */
public record SearchError(String taskId, String code, String message) {
}
