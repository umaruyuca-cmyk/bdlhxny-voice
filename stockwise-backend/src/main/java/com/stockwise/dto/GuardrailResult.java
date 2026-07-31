package com.stockwise.dto;

/**
 * 护栏检查结果。
 *
 * @param passed 是否通过（true 放行，false 拦截）
 * @param reason 未通过原因，供日志与前端展示
 */
public record GuardrailResult(boolean passed, String reason) {
}
