package com.bdlh.runtime.agent.react;

import java.util.Map;
import java.util.function.Supplier;

/**
 * 表示由确定性 Route 规划出的单次工具 Action，执行函数不会被模型动态替换。
 */
public record ReactToolAction(
        String toolName,
        Map<String, Object> arguments,
        String reasoningSummary,
        Supplier<String> execution
) {

    public ReactToolAction {
        if (toolName == null || toolName.isBlank()) {
            throw new IllegalArgumentException("ReAct 工具名不能为空");
        }
        arguments = arguments == null ? Map.of() : Map.copyOf(arguments);
        reasoningSummary = reasoningSummary == null ? "" : reasoningSummary;
        if (execution == null) {
            throw new IllegalArgumentException("ReAct 工具执行函数不能为空");
        }
    }
}
