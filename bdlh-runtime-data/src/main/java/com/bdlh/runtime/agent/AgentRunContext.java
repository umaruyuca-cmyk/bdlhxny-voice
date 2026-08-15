package com.bdlh.runtime.agent;

import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 单次 Agent Run 的进程内上下文，负责生成严格递增的步骤号和工具调用计数。
 */
public class AgentRunContext {

    private final UUID runId;
    private final Long userId;
    private final int maxToolCalls;
    private final AtomicInteger stepSequence = new AtomicInteger();
    private final AtomicInteger toolCallCount = new AtomicInteger();

    public AgentRunContext(UUID runId) {
        this(runId, null, Integer.MAX_VALUE);
    }

    public AgentRunContext(UUID runId, int maxToolCalls) {
        this(runId, null, maxToolCalls);
    }

    public AgentRunContext(UUID runId, Long userId, int maxToolCalls) {
        this.runId = runId;
        this.userId = userId;
        this.maxToolCalls = Math.max(0, maxToolCalls);
    }

    public UUID runId() {
        return runId;
    }

    public Long userId() {
        return userId;
    }

    public int nextStep() {
        return stepSequence.incrementAndGet();
    }

    public int incrementToolCallCount() {
        return toolCallCount.incrementAndGet();
    }

    public int toolCallCount() {
        return toolCallCount.get();
    }

    /**
     * 判断本轮是否仍有工具预算，避免显式执行链绕过 Skill 的调用上限。
     */
    public boolean toolBudgetAvailable() {
        return toolCallCount.get() < maxToolCalls;
    }
}
