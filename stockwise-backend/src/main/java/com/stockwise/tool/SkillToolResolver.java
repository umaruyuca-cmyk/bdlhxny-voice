package com.stockwise.tool;

import com.stockwise.agent.AgentRunContext;
import com.stockwise.service.AgentRunService;
import com.stockwise.skill.SkillDefinition;
import org.springframework.ai.chat.model.ToolContext;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.definition.ToolDefinition;
import org.springframework.ai.tool.metadata.ToolMetadata;
import org.springframework.ai.tool.method.MethodToolCallbackProvider;
import org.springframework.stereotype.Component;

import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 按 Skill 的工具白名单生成本次推理可用的 ToolCallback，并附加调用次数与重复调用预算。
 * 权限与预算在代码层执行，避免仅依赖提示词约束模型行为。
 */
@Component
public class SkillToolResolver {

    private static final int DEFAULT_MAX_TOOL_CALLS = 4;
    private static final int DEFAULT_MAX_SAME_TOOL_CALL = 1;

    private final Map<String, ToolCallback> callbacks;
    private final AgentRunService agentRunService;

    public SkillToolResolver(StockTools stockTools, AgentRunService agentRunService) {
        this.agentRunService = agentRunService;
        // 1. 扫描 StockTools 上的 @Tool 方法并按工具名建立不可变索引
        ToolCallback[] discovered = MethodToolCallbackProvider.builder()
                .toolObjects(stockTools)
                .build()
                .getToolCallbacks();
        Map<String, ToolCallback> index = new LinkedHashMap<>();
        Arrays.stream(discovered).forEach(callback ->
                index.put(callback.getToolDefinition().name(), callback));
        this.callbacks = Map.copyOf(index);
    }

    /**
     * 解析指定 Skill 的工具子集，每次调用创建独立预算，避免不同请求之间共享计数。
     */
    public List<ToolCallback> resolve(SkillDefinition skill) {
        return resolve(skill, null);
    }

    /**
     * 解析指定 Skill 的工具子集，并把每次工具调用关联到当前 Agent Run。
     */
    public List<ToolCallback> resolve(SkillDefinition skill, AgentRunContext runContext) {
        int maxCalls = intConstraint(skill, "maxToolCalls", DEFAULT_MAX_TOOL_CALLS);
        int maxSameCall = intConstraint(skill, "maxSameToolCall", DEFAULT_MAX_SAME_TOOL_CALL);
        ToolExecutionBudget budget = new ToolExecutionBudget(maxCalls, maxSameCall);

        // 1. 严格按白名单顺序解析工具，配置了未知工具时立即失败
        return skill.availableTools().stream()
                .map(name -> {
                    ToolCallback callback = callbacks.get(name);
                    if (callback == null) {
                        throw new IllegalStateException("Skill " + skill.name() + " 配置了未知工具: " + name);
                    }
                    return (ToolCallback) new BudgetedToolCallback(
                            callback, budget, runContext, agentRunService);
                })
                .toList();
    }

    private int intConstraint(SkillDefinition skill, String name, int defaultValue) {
        Object value = skill.constraints().get(name);
        if (value instanceof Number number) {
            return Math.max(0, number.intValue());
        }
        return defaultValue;
    }

    /**
     * 单次 Agent 推理的工具调用预算，记录总调用数与相同工具参数的调用次数。
     */
    private static final class ToolExecutionBudget {

        private final int maxCalls;
        private final int maxSameCall;
        private final Map<String, Integer> fingerprints = new LinkedHashMap<>();
        private int calls;

        private ToolExecutionBudget(int maxCalls, int maxSameCall) {
            this.maxCalls = maxCalls;
            this.maxSameCall = maxSameCall;
        }

        /**
         * 在工具真正执行前占用预算；拒绝时返回机器可识别的错误码。
         */
        private synchronized String acquire(String toolName, String arguments) {
            if (calls >= maxCalls) {
                return "TOOL_CALL_BUDGET_EXCEEDED";
            }
            String fingerprint = toolName + "\n" + (arguments == null ? "" : arguments.trim());
            int sameCalls = fingerprints.getOrDefault(fingerprint, 0);
            if (sameCalls >= maxSameCall) {
                return "DUPLICATE_TOOL_CALL_BLOCKED";
            }
            // 1. 只有允许执行的调用才计入总预算和重复调用计数
            calls++;
            fingerprints.put(fingerprint, sameCalls + 1);
            return null;
        }
    }

    /**
     * ToolCallback 装饰器，在委托执行前应用本次请求的预算策略。
     */
    private record BudgetedToolCallback(ToolCallback delegate,
                                        ToolExecutionBudget budget,
                                        AgentRunContext runContext,
                                        AgentRunService agentRunService)
            implements ToolCallback {

        @Override
        public ToolDefinition getToolDefinition() {
            return delegate.getToolDefinition();
        }

        @Override
        public ToolMetadata getToolMetadata() {
            return delegate.getToolMetadata();
        }

        @Override
        public String call(String toolInput) {
            String rejection = budget.acquire(getToolDefinition().name(), toolInput);
            if (rejection != null) {
                recordRejection(toolInput, rejection);
                return error(rejection);
            }
            if (runContext == null) {
                return delegate.call(toolInput);
            }
            return agentRunService.executeTool(
                    runContext,
                    getToolDefinition().name(),
                    toolInput,
                    () -> delegate.call(toolInput));
        }

        @Override
        public String call(String toolInput, ToolContext toolContext) {
            String rejection = budget.acquire(getToolDefinition().name(), toolInput);
            if (rejection != null) {
                recordRejection(toolInput, rejection);
                return error(rejection);
            }
            if (runContext == null) {
                return delegate.call(toolInput, toolContext);
            }
            return agentRunService.executeTool(
                    runContext,
                    getToolDefinition().name(),
                    toolInput,
                    () -> delegate.call(toolInput, toolContext));
        }

        private void recordRejection(String toolInput, String errorCode) {
            if (runContext != null) {
                agentRunService.recordPolicyRejection(
                        runContext, getToolDefinition().name(), errorCode, toolInput);
            }
        }

        private String error(String code) {
            return "{\"success\":false,\"error\":\"" + code
                    + "\",\"message\":\"工具调用被 Skill 预算策略拒绝，请基于已有 Observation 回答或向用户追问。\"}";
        }
    }
}
