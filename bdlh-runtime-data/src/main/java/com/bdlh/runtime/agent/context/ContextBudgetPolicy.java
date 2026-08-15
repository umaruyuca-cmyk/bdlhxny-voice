package com.bdlh.runtime.agent.context;

import com.bdlh.runtime.agent.routing.ModelPolicy;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * 按模型等级分配对话记忆预算，使本地模型与付费分析模型使用不同的受控上下文窗口。
 */
@Component
public class ContextBudgetPolicy {

    private final int maxMessages;
    private final int localMaxMemoryTokens;
    private final int paidMaxMemoryTokens;
    private final int maxMessageTokens;
    private final int maxSummaries;
    private final int maxSummaryTokens;

    public ContextBudgetPolicy(
            @Value("${bdlh_runtime.context-window.max-messages:10}") int maxMessages,
            @Value("${bdlh_runtime.context-window.local-max-memory-tokens:2000}") int localMaxMemoryTokens,
            @Value("${bdlh_runtime.context-window.paid-max-memory-tokens:4000}") int paidMaxMemoryTokens,
            @Value("${bdlh_runtime.context-window.max-message-tokens:800}") int maxMessageTokens,
            @Value("${bdlh_runtime.context-window.max-summaries:3}") int maxSummaries,
            @Value("${bdlh_runtime.context-window.max-summary-tokens:900}") int maxSummaryTokens) {
        this.maxMessages = positive(maxMessages, 10);
        this.localMaxMemoryTokens = positive(localMaxMemoryTokens, 2000);
        this.paidMaxMemoryTokens = positive(paidMaxMemoryTokens, 4000);
        this.maxMessageTokens = positive(maxMessageTokens, 800);
        this.maxSummaries = positive(maxSummaries, 3);
        this.maxSummaryTokens = positive(maxSummaryTokens, 900);
    }

    /**
     * 根据本轮最高模型等级返回记忆预算，模板与本地回答使用较小窗口。
     */
    public ContextBudget resolve(ModelPolicy modelPolicy) {
        int memoryTokens = modelPolicy == ModelPolicy.PAID_AFTER_VALIDATED_SKILL
                ? paidMaxMemoryTokens
                : localMaxMemoryTokens;
        return new ContextBudget(maxMessages, memoryTokens,
                Math.min(maxMessageTokens, memoryTokens), maxSummaries,
                Math.min(maxSummaryTokens, memoryTokens));
    }

    private int positive(int value, int fallback) {
        return value > 0 ? value : fallback;
    }

    /**
     * 描述一次上下文组装可使用的消息数、记忆 Token 与摘要预算。
     */
    public record ContextBudget(
            int maxMessages,
            int maxMemoryTokens,
            int maxMessageTokens,
            int maxSummaries,
            int maxSummaryTokens
    ) {
    }
}
