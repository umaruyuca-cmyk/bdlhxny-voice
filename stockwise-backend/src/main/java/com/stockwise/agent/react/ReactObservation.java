package com.stockwise.agent.react;

/**
 * 保存一次工具执行的完整结果和受限工作记忆摘要，完整结果仅供本轮校验与模型消费。
 */
public record ReactObservation(
        String toolName,
        String output,
        String compactOutput,
        long durationMs
) {
}
